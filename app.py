import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, date
import json

# Page configuration
st.set_page_config(
    page_title="Tutor Management System",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(90deg, #2563eb 0%, #1e40af 100%);
        padding: 1.5rem;
        border-radius: 10px;
        color: white;
        margin-bottom: 2rem;
    }
    .class-card {
        background: white;
        padding: 1.5rem;
        border-radius: 10px;
        border: 1px solid #e5e7eb;
        margin-bottom: 1rem;
        transition: box-shadow 0.3s;
    }
    .class-card:hover {
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .topic-card {
        background: #f9fafb;
        padding: 1rem;
        border-radius: 8px;
        border-left: 4px solid #3b82f6;
        margin-bottom: 1rem;
    }
    .completed {
        border-left-color: #10b981;
        background: #f0fdf4;
    }
    .stButton > button {
        width: 100%;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'tutor_id' not in st.session_state:
    st.session_state.tutor_id = None
if 'tutor_name' not in st.session_state:
    st.session_state.tutor_name = None
if 'current_view' not in st.session_state:
    st.session_state.current_view = 'dashboard'
if 'show_memo_dialog' not in st.session_state:
    st.session_state.show_memo_dialog = None
if 'selected_student' not in st.session_state:
    st.session_state.selected_student = None
if 'admin_mode' not in st.session_state:
    st.session_state.admin_mode = False
if 'locally_completed' not in st.session_state:
    # Tracks plan IDs marked done this session so UI updates instantly
    st.session_state.locally_completed = set()

def get_google_sheets_client():
    """Create a fresh authenticated gspread client.
    Service account credentials never expire, so this is safe to call per-write.
    For reads, load_sheet_data caches results to avoid quota hits."""
    try:
        creds_dict = st.secrets["gcp_service_account"]
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(credentials)
        return client
    except Exception as e:
        st.error(f"Error connecting to Google Sheets: {str(e)}")
        return None

# Cache reads aggressively - 5 min TTL means at most 12 reads/hour per sheet.
# Writes always bypass this cache and call the API directly.
@st.cache_data(ttl=300)
def load_sheet_data(sheet_name):
    """Load data from a specific sheet. Results cached for 5 minutes to stay within quota."""
    try:
        client = get_google_sheets_client()
        if not client:
            return None

        spreadsheet = client.open_by_key(st.secrets["spreadsheet_id"])

        try:
            worksheet = spreadsheet.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            all_sheets = [ws.title for ws in spreadsheet.worksheets()]
            for ws_name in all_sheets:
                if ws_name.strip() == sheet_name.strip():
                    worksheet = spreadsheet.worksheet(ws_name)
                    break
            else:
                # Don't st.error for missing optional sheets - just return None silently
                return None

        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        df.columns = df.columns.str.strip()
        return df
    except Exception as e:
        # Only show error for non-quota issues so quota errors don't spam the UI
        err = str(e)
        if '429' not in err:
            st.error(f"Error loading {sheet_name}: {err}")
        return None

def authenticate_tutor(tutor_id, password):
    """Authenticate tutor with ID and password"""
    tutors_df = load_sheet_data("Tutors")
    
    if tutors_df is None or tutors_df.empty:
        return False, "Cannot access Tutors database"
    
    if 'Tutor_ID' not in tutors_df.columns:
        return False, "Tutors sheet missing 'Tutor_ID' column"
    
    if 'Password' not in tutors_df.columns:
        return False, f"Tutors sheet missing 'Password' column. Found columns: {', '.join(tutors_df.columns)}"
    
    tutor = tutors_df[tutors_df['Tutor_ID'].astype(str).str.strip() == str(tutor_id).strip()]
    
    if tutor.empty:
        return False, "Invalid Tutor ID"
    
    stored_password = str(tutor.iloc[0]['Password']).strip()
    if stored_password == str(password).strip():
        tutor_name = tutor.iloc[0].get('Name', tutor_id) if 'Name' in tutor.columns else tutor_id
        log_login_activity(tutor_id, str(tutor_name))
        return True, str(tutor_name)
    else:
        return False, "Invalid password"

def log_login_activity(tutor_id, tutor_name):
    """Log tutor login activity to Usage_Log sheet"""
    try:
        client = get_google_sheets_client()
        spreadsheet = client.open_by_key(st.secrets["spreadsheet_id"])
        
        try:
            worksheet = spreadsheet.worksheet("Usage_Log")
        except gspread.exceptions.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(title="Usage_Log", rows="1000", cols="6")
            worksheet.append_row(['Timestamp', 'Tutor_ID', 'Tutor_Name', 'Action', 'Date', 'Details'])
        
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        date_only = datetime.now().strftime('%Y-%m-%d')
        worksheet.append_row([timestamp, tutor_id, tutor_name, 'Login', date_only, ''])
        
    except Exception as e:
        print(f"Error logging activity: {str(e)}")
        pass

def log_topic_completion(tutor_id, plan_id, student_id):
    """Log when a tutor marks a topic as complete"""
    try:
        client = get_google_sheets_client()
        if not client:
            print("No Google Sheets client available")
            return
            
        spreadsheet = client.open_by_key(st.secrets["spreadsheet_id"])
        
        try:
            worksheet = spreadsheet.worksheet("Usage_Log")
        except gspread.exceptions.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(title="Usage_Log", rows="1000", cols="6")
            worksheet.append_row(['Timestamp', 'Tutor_ID', 'Tutor_Name', 'Action', 'Date', 'Details'])
        
        tutor_name = str(tutor_id)
        try:
            tutors_df = load_sheet_data("Tutors")
            if tutors_df is not None and not tutors_df.empty:
                tutor = tutors_df[tutors_df['Tutor_ID'].astype(str).str.strip() == str(tutor_id).strip()]
                if not tutor.empty and 'Name' in tutor.columns:
                    tutor_name = str(tutor.iloc[0]['Name'])
        except Exception as e:
            print(f"Error getting tutor name: {e}")
        
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        date_only = datetime.now().strftime('%Y-%m-%d')
        details = f"Student: {student_id}, Plan: {plan_id}"
        
        worksheet.append_row([timestamp, str(tutor_id), tutor_name, 'Topic_Completed', date_only, details])
        print(f"Successfully logged completion: {tutor_id}, {plan_id}")
        
    except Exception as e:
        print(f"Error logging completion: {str(e)}")
        import traceback
        traceback.print_exc()

def authenticate_admin(password):
    """Authenticate admin access"""
    admin_password = st.secrets.get("admin_password", "admin123")
    return password == admin_password

def get_tutor_classes(tutor_id):
    """Get all classes for a specific tutor"""
    schedule_df = load_sheet_data("Schedule")
    
    if schedule_df is None or schedule_df.empty:
        return pd.DataFrame()
    
    tutor_classes = schedule_df[schedule_df['Tutor_ID'].astype(str).str.strip() == str(tutor_id).strip()].copy()
    
    students_df = load_sheet_data("Students ")
    if students_df is None or students_df.empty:
        students_df = load_sheet_data("Students")
    
    if students_df is not None and not students_df.empty:
        # Build name map keyed by (Student_ID, Subject) so we get the right row
        # when a student appears multiple times with different subjects
        def get_student_name(row):
            sid = str(row['Student_ID']).strip()
            subj = str(row.get('Subject', '')).strip()
            # Try exact match on student_id + subject first
            if subj and 'Subject' in students_df.columns:
                match = students_df[
                    (students_df['Student_ID'].astype(str).str.strip() == sid) &
                    (students_df['Subject'].astype(str).str.strip() == subj)
                ]
                if not match.empty and 'Student_Name' in match.columns:
                    return str(match.iloc[0]['Student_Name']).strip()
            # Fallback: any row for this student
            match = students_df[students_df['Student_ID'].astype(str).str.strip() == sid]
            if not match.empty and 'Student_Name' in match.columns:
                return str(match.iloc[0]['Student_Name']).strip()
            return sid

        tutor_classes['Student_Name'] = tutor_classes.apply(get_student_name, axis=1)
    
    return tutor_classes

def parse_date(date_str):
    """Parse date from various formats"""
    if pd.isna(date_str):
        return None
    
    date_str = str(date_str).strip()
    formats = ['%d/%m/%Y', '%Y-%m-%d', '%m/%d/%Y', '%d-%m-%Y']
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except:
            continue
    
    return None

def read_progress_tracker_fresh():
    """Read Progress_Tracker directly from sheet, bypassing cache.
    Used for checking completions so marks show immediately after saving."""
    try:
        client = get_google_sheets_client()
        if not client:
            return None
        spreadsheet = client.open_by_key(st.secrets["spreadsheet_id"])
        try:
            worksheet = spreadsheet.worksheet("Progress_Tracker")
        except gspread.exceptions.WorksheetNotFound:
            return None
        data = worksheet.get_all_records()
        if not data:
            return None
        df = pd.DataFrame(data)
        df.columns = df.columns.str.strip()
        return df
    except Exception:
        return None


def get_student_plan(student_id, subject_filter=None):
    """Get learning plan for a specific student - automatically generated from curriculum"""
    try:
        students_df = load_sheet_data("Students ")
        if students_df is None:
            students_df = load_sheet_data("Students")
        
        curriculum_df = load_sheet_data("Curriculum_Library")
        # Always read Progress_Tracker fresh (no cache) so completed topics
        # show immediately after being marked, without waiting for TTL to expire
        progress_df = read_progress_tracker_fresh()
        
        if students_df is None or curriculum_df is None:
            return pd.DataFrame()
        
        if subject_filter:
            print(f"DEBUG: Filtering by Student_ID={student_id} AND Subject={subject_filter}")
            print(f"DEBUG: Students sheet has {len(students_df)} rows")
            print(f"DEBUG: Students sheet columns: {students_df.columns.tolist()}")
            
            if 'Subject' not in students_df.columns:
                print("WARNING: Subject column not found in Students sheet!")
                student = students_df[students_df['Student_ID'].astype(str).str.strip() == str(student_id).strip()]
            else:
                student = students_df[
                    (students_df['Student_ID'].astype(str).str.strip() == str(student_id).strip()) &
                    (students_df['Subject'].astype(str).str.strip() == str(subject_filter).strip())
                ]
                print(f"DEBUG: Found {len(student)} matching student records")
        else:
            student = students_df[students_df['Student_ID'].astype(str).str.strip() == str(student_id).strip()]
        
        if student.empty:
            print(f"ERROR: No student found with ID={student_id}, Subject={subject_filter}")
            return pd.DataFrame()
        
        student_grade = str(student.iloc[0].get('Grade', '')).strip()
        student_subject = str(student.iloc[0].get('Subject', '')).strip()
        
        print(f"DEBUG: Student Grade={student_grade}, Subject={student_subject}")
        print(f"DEBUG: Curriculum has {len(curriculum_df)} topics")
        
        if 'Grade' not in curriculum_df.columns or 'Subject' not in curriculum_df.columns:
            print("WARNING: Grade or Subject column missing in Curriculum_Library!")
            student_topics = curriculum_df.copy()
        else:
            student_topics = curriculum_df[
                (curriculum_df['Grade'].astype(str).str.strip() == student_grade) &
                (curriculum_df['Subject'].astype(str).str.strip() == student_subject)
            ].copy()
            print(f"DEBUG: Filtered to {len(student_topics)} topics for Grade={student_grade}, Subject={student_subject}")
        
        if student_topics.empty:
            # No topics found for this grade+subject — return empty, don't show all topics
            print(f"WARNING: No curriculum topics found for Grade={student_grade}, Subject={student_subject}")
            return pd.DataFrame()

        plans = []
        
        for _, topic in student_topics.iterrows():
            topic_id = str(topic['Topic_ID']).strip()
            
            is_completed = False
            completed_by = ''
            completed_at = ''
            
            if progress_df is not None and not progress_df.empty:
                completion = progress_df[
                    (progress_df['Student_ID'].astype(str).str.strip() == str(student_id).strip()) &
                    (progress_df['Topic_ID'].astype(str).str.strip() == topic_id)
                ]
                
                if 'Subject' in progress_df.columns and not completion.empty:
                    completion = completion[
                        completion['Subject'].astype(str).str.strip() == student_subject
                    ]
                
                if not completion.empty:
                    is_completed = True
                    completed_by = completion.iloc[0].get('Completed_By', '')
                    date_val = completion.iloc[0].get('Date_Completed', '')
                    completed_at = formatDate(date_val) if date_val else ''
            
            plan_id = f"{student_id}|||{student_subject}|||{topic_id}"
            
            plans.append({
                'planId': plan_id,
                'topicId': topic_id,
                'subject': student_subject,
                'subUnitName': str(topic.get('Sub_Unit_Name', 'Unknown Topic')),
                'unitName': str(topic.get('Unit_Name', '')),
                'status': 'Completed' if is_completed else 'Pending',
                'completedBy': str(completed_by),
                'dateCompleted': str(completed_at),
                'contentLink': str(topic.get('Textbook_Ref', ''))
            })
        
        return pd.DataFrame(plans)
        
    except Exception as e:
        print(f"Error in get_student_plan: {str(e)}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame()

def formatDate(date_val):
    """Format date value"""
    if pd.isna(date_val) or not date_val:
        return ''
    
    date_str = str(date_val).strip()
    if not date_str:
        return ''
    
    try:
        parsed = parse_date(date_str)
        if parsed:
            return parsed.strftime('%d/%m/%Y')
    except:
        pass
    
    return date_str

def save_tutor_memo(student_id, class_date, memo_text):
    """Save tutor memo to the Schedule sheet"""
    try:
        client = get_google_sheets_client()
        spreadsheet = client.open_by_key(st.secrets["spreadsheet_id"])
        worksheet = spreadsheet.worksheet("Schedule")
        
        data = worksheet.get_all_records()
        
        for idx, row in enumerate(data):
            if (str(row.get('Student_ID')).strip() == str(student_id).strip() and 
                str(row.get('Date')).strip() == str(class_date).strip()):
                
                row_num = idx + 2
                
                headers = worksheet.row_values(1)
                if 'Tutor_Memo' in headers:
                    memo_col = headers.index('Tutor_Memo') + 1
                    worksheet.update_cell(row_num, memo_col, memo_text)
                    st.cache_data.clear()
                    return True, "Memo saved successfully!"
                else:
                    return False, "Tutor_Memo column not found in Schedule sheet"
        
        return False, "Class not found in schedule"
    except Exception as e:
        return False, f"Error saving memo: {str(e)}"

def mark_topic_complete(plan_id, tutor_id):
    """Mark a topic as completed - saves to Progress_Tracker sheet"""
    # Parse plan_id: format is StudentID|||Subject|||TopicID
    # Using ||| as delimiter since Student_ID, Subject and Topic_ID can all contain hyphens
    if '|||' in plan_id:
        parts = plan_id.split('|||')
        if len(parts) == 3:
            student_id = parts[0].strip()
            subject = parts[1].strip()
            topic_id = parts[2].strip()
        else:
            return False, f"Invalid Plan ID format (expected 3 parts): {plan_id}"
    else:
        # Legacy fallback for old hyphen-based IDs
        parts = plan_id.split('-', 2)
        if len(parts) == 3:
            student_id = parts[0].strip()
            subject = parts[1].strip()
            topic_id = parts[2].strip()
        elif len(parts) == 2:
            student_id = parts[0].strip()
            topic_id = parts[1].strip()
            subject = ''
        else:
            return False, f"Invalid Plan ID format: {plan_id}"

    try:
        client = get_google_sheets_client()
        if not client:
            return False, "Cannot connect to Google Sheets - check service account credentials"

        spreadsheet = client.open_by_key(st.secrets["spreadsheet_id"])

        # Get or create Progress_Tracker sheet
        try:
            worksheet = spreadsheet.worksheet("Progress_Tracker")
        except gspread.exceptions.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(title="Progress_Tracker", rows="1000", cols="5")
            worksheet.append_row(['Student_ID', 'Topic_ID', 'Subject', 'Completed_By', 'Date_Completed'])

        all_data = worksheet.get_all_values()
        current_date = datetime.now().strftime('%d/%m/%Y')

        if len(all_data) > 1:
            headers = all_data[0]
            data_rows = all_data[1:]

            # Get column indices safely
            try:
                student_col = headers.index('Student_ID')
            except ValueError:
                student_col = 0
            try:
                topic_col = headers.index('Topic_ID')
            except ValueError:
                topic_col = 1
            try:
                subject_col = headers.index('Subject')
            except ValueError:
                subject_col = -1
            try:
                completed_by_col = headers.index('Completed_By')
            except ValueError:
                completed_by_col = 3
            try:
                date_col_idx = headers.index('Date_Completed')
            except ValueError:
                date_col_idx = 4

            for row_idx, row in enumerate(data_rows):
                # Pad short rows
                while len(row) <= max(student_col, topic_col):
                    row.append('')

                row_student = str(row[student_col]).strip()
                row_topic = str(row[topic_col]).strip()

                if row_student != str(student_id).strip() or row_topic != str(topic_id).strip():
                    continue

                # If subject column exists, also match subject
                if subject and subject_col >= 0 and len(row) > subject_col:
                    if str(row[subject_col]).strip() != str(subject).strip():
                        continue

                # Found existing row - update it using batch_update
                sheet_row = row_idx + 2  # +1 for header, +1 for 1-based index
                updates = [
                    {'range': gspread.utils.rowcol_to_a1(sheet_row, completed_by_col + 1),
                     'values': [[str(tutor_id)]]},
                    {'range': gspread.utils.rowcol_to_a1(sheet_row, date_col_idx + 1),
                     'values': [[current_date]]},
                ]
                if subject and subject_col >= 0:
                    updates.append({
                        'range': gspread.utils.rowcol_to_a1(sheet_row, subject_col + 1),
                        'values': [[str(subject)]]
                    })
                worksheet.batch_update(updates)

                log_topic_completion(tutor_id, plan_id, student_id)
                st.cache_data.clear()
                load_sheet_data.clear()
                return True, "Topic marked as completed!"

        # No existing row found - append new one
        new_row = [str(student_id), str(topic_id), str(subject), str(tutor_id), current_date]
        result = worksheet.append_row(new_row, value_input_option='RAW')

        # Verify write succeeded by checking the response
        if result is None:
            return False, "append_row returned None - write may have failed silently"

        log_topic_completion(tutor_id, plan_id, student_id)
        st.cache_data.clear()
        load_sheet_data.clear()
        return True, f"Saved! Row: {new_row}"

    except gspread.exceptions.APIError as e:
        import traceback
        traceback.print_exc()
        return False, f"Google API error: {str(e)}"
    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, f"Unexpected error: {type(e).__name__}: {str(e)}"

# Login Page
def show_login():
    st.markdown('<div class="main-header"><h1>📚 Tutor Management System</h1><p>Please login to continue</p></div>', unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col3:
        if st.button("🔐 Admin Access", use_container_width=True):
            st.session_state.admin_mode = True
            st.rerun()
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown("### 🔐 Login")
        
        with st.form("login_form"):
            tutor_id = st.text_input("Tutor ID", placeholder="Enter your Tutor ID")
            password = st.text_input("Password", type="password", placeholder="Enter your password")
            submit = st.form_submit_button("Login", use_container_width=True)
            
            if submit:
                if not tutor_id or not password:
                    st.error("Please enter both Tutor ID and Password")
                else:
                    success, result = authenticate_tutor(tutor_id, password)
                    
                    if success:
                        st.session_state.logged_in = True
                        st.session_state.tutor_id = tutor_id
                        st.session_state.tutor_name = result
                        st.rerun()
                    else:
                        st.error(result)
        
        st.markdown("---")
        
        with st.expander("🔍 Debug Info (Click if login fails)"):
            col1, col2 = st.columns(2)
            
            with col1:
                if st.button("Check Tutors Sheet"):
                    tutors_df = load_sheet_data("Tutors")
                    if tutors_df is not None:
                        st.success(f"✅ Tutors sheet found with {len(tutors_df)} rows")
                        st.write("**Columns found:**", list(tutors_df.columns))
                        st.write("**Sample data (first 3 rows):**")
                        st.dataframe(tutors_df.head(3))
                    else:
                        st.error("❌ Cannot access Tutors sheet")
            
            with col2:
                if st.button("Check System Setup"):
                    st.write("**Checking sheets...**")
                    
                    students = load_sheet_data("Students ") or load_sheet_data("Students")
                    curriculum = load_sheet_data("Curriculum_Library")
                    schedule = load_sheet_data("Schedule")
                    progress_tracker = load_sheet_data("Progress_Tracker")
                    
                    st.write("✅ Students:" if students is not None else "❌ Students:", 
                             "Found" if students is not None else "Missing")
                    st.write("✅ Curriculum:" if curriculum is not None else "❌ Curriculum:", 
                             "Found" if curriculum is not None else "Missing")
                    st.write("✅ Schedule:" if schedule is not None else "❌ Schedule:", 
                             "Found" if schedule is not None else "Missing")
                    
                    if progress_tracker is not None:
                        st.success("✅ Progress_Tracker: Found")
                    else:
                        st.error("❌ Progress_Tracker sheet not found")
        
        st.info("💡 **First time setup required:**\n\n1. Create a 'Tutors' sheet with columns: Tutor_ID, Password, Name\n2. Add your credentials there\n3. Configure Google Sheets API (see deployment guide)")

# Dashboard
def show_dashboard():
    if st.session_state.show_memo_dialog:
        show_memo_dialog()
        return
    
    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        st.markdown(f'<div class="main-header"><h1>📚 My Classes</h1><p>Welcome back, {st.session_state.tutor_name}!</p></div>', unsafe_allow_html=True)
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔄 Refresh", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
    with col3:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.tutor_id = None
            st.rerun()
    
    classes_df = get_tutor_classes(st.session_state.tutor_id)
    
    if classes_df.empty:
        st.warning("No classes found for your Tutor ID")
        return
    
    tab1, tab2, tab3 = st.tabs(["📅 Today's Classes", "🔜 Upcoming (7 Days)", "📚 Past Classes"])
    
    today = date.today()
    from datetime import timedelta
    next_7_days = today + timedelta(days=7)
    
    with tab1:
        today_classes = classes_df[classes_df['Date'].apply(lambda x: False if parse_date(x) is None else (parse_date(x) == today))]
        
        if today_classes.empty:
            st.info("No classes scheduled for today")
        else:
            st.markdown(f"### 📆 {today.strftime('%A, %B %d, %Y')}")
            for _, cls in today_classes.iterrows():
                show_class_card(cls, f"today_{_}")
    
    with tab2:
        upcoming_classes = classes_df[classes_df['Date'].apply(
            lambda x: False if parse_date(x) is None else (today < parse_date(x) <= next_7_days)
        )]
        upcoming_classes = upcoming_classes.sort_values('Date', ascending=True)
        
        if upcoming_classes.empty:
            st.info("No upcoming classes in the next 7 days")
        else:
            for date_val in upcoming_classes['Date'].unique():
                date_obj = parse_date(date_val)
                if date_obj:
                    days_diff = (date_obj - today).days
                    if days_diff == 1:
                        day_label = "Tomorrow"
                    else:
                        day_label = f"In {days_diff} days"
                    
                    st.markdown(f"### 📆 {date_obj.strftime('%A, %B %d, %Y')} ({day_label})")
                    
                    day_classes = upcoming_classes[upcoming_classes['Date'] == date_val]
                    for idx, cls in day_classes.iterrows():
                        show_class_card(cls, f"upcoming_{date_val}_{idx}")
                    
                    st.markdown("---")
    
    with tab3:
        past_classes = classes_df[classes_df['Date'].apply(lambda x: False if parse_date(x) is None else (parse_date(x) < today))]
        past_classes = past_classes.sort_values('Date', ascending=False)
        
        if past_classes.empty:
            st.info("No past classes found")
        else:
            recent_past = past_classes.head(50)
            
            for date_val in recent_past['Date'].unique():
                date_obj = parse_date(date_val)
                if date_obj:
                    days_ago = (today - date_obj).days
                    if days_ago == 1:
                        day_label = "Yesterday"
                    else:
                        day_label = f"{days_ago} days ago"
                    
                    st.markdown(f"### 📆 {date_obj.strftime('%A, %B %d, %Y')} ({day_label})")
                    
                    day_classes = recent_past[recent_past['Date'] == date_val]
                    for idx, cls in day_classes.iterrows():
                        show_class_card(cls, f"past_{date_val}_{idx}")
                    
                    st.markdown("---")

def show_class_card(cls, unique_key):
    """Display a class card"""
    with st.container():
        st.markdown('<div class="class-card">', unsafe_allow_html=True)
        
        col1, col2 = st.columns([3, 1])
        
        with col1:
            st.markdown(f"### {cls.get('Student_Name', cls['Student_ID'])}")
            st.markdown(f"📅 **Date:** {cls['Date']} | 🕐 **Time:** {cls.get('Start_Time', 'N/A')} - {cls.get('End_Time', 'N/A')}")
            st.markdown(f"📖 **Subject:** {cls['Subject']}")
            st.markdown(f"🆔 **Student ID:** {cls['Student_ID']}")
            
            if pd.notna(cls.get('Tutor_Memo')) and str(cls.get('Tutor_Memo')).strip():
                st.markdown(f"📝 **Memo:** {cls.get('Tutor_Memo')}")
        
        with col2:
            if st.button("📝 Memo", key=f"memo_{unique_key}", use_container_width=True):
                st.session_state.show_memo_dialog = {
                    'student_id': cls['Student_ID'],
                    'student_name': cls.get('Student_Name', cls['Student_ID']),
                    'date': cls['Date'],
                    'existing_memo': cls.get('Tutor_Memo', '')
                }
                st.rerun()
            
            if st.button("View Progress →", key=f"progress_{unique_key}", use_container_width=True):
                st.session_state.current_view = 'student'
                st.session_state.selected_student = {
                    'id': cls['Student_ID'],
                    'name': cls.get('Student_Name', cls['Student_ID']),
                    'subject': cls.get('Subject', '')
                }
                st.rerun()
        
        st.markdown('</div>', unsafe_allow_html=True)

def show_memo_dialog():
    """Show dialog for adding/editing memo"""
    memo_data = st.session_state.show_memo_dialog
    
    st.markdown('<div class="main-header"><h1>📝 Add/Edit Memo</h1></div>', unsafe_allow_html=True)
    
    st.markdown(f"### {memo_data['student_name']}")
    st.markdown(f"📅 **Date:** {memo_data['date']}")
    st.markdown("---")
    
    memo_text = st.text_area(
        "Class Memo",
        value=memo_data.get('existing_memo', ''),
        height=200,
        placeholder="Enter notes about the class: topics covered, student performance, homework assigned, etc.",
        help="This memo will be saved to the Schedule sheet"
    )
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("💾 Save Memo", use_container_width=True):
            if memo_text.strip():
                success, message = save_tutor_memo(
                    memo_data['student_id'],
                    memo_data['date'],
                    memo_text.strip()
                )
                
                if success:
                    st.success(message)
                    st.session_state.show_memo_dialog = None
                    st.rerun()
                else:
                    st.error(message)
            else:
                st.warning("Please enter a memo before saving")
    
    with col2:
        if st.button("Cancel", use_container_width=True):
            st.session_state.show_memo_dialog = None
            st.rerun()

# Admin Panel
def show_admin_login():
    """Admin login page"""
    st.markdown('<div class="main-header"><h1>🔐 Admin Panel</h1><p>Administrator Access</p></div>', unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        if st.button("← Back to Tutor Login"):
            st.session_state.admin_mode = False
            st.rerun()
        
        st.markdown("### 🔑 Admin Authentication")
        
        with st.form("admin_login_form"):
            admin_password = st.text_input("Admin Password", type="password", placeholder="Enter admin password")
            submit = st.form_submit_button("Login as Admin", use_container_width=True)
            
            if submit:
                if not admin_password:
                    st.error("Please enter admin password")
                else:
                    if authenticate_admin(admin_password):
                        st.session_state.logged_in = True
                        st.session_state.tutor_id = 'ADMIN'
                        st.session_state.tutor_name = 'Administrator'
                        st.rerun()
                    else:
                        st.error("Invalid admin password")
        
        st.info("💡 Default admin password is set in Streamlit secrets. Contact system administrator if you don't have it.")

def get_team_for_tutor(tutor_id_str, tutors_df):
    """Return the team name for a given tutor, or 'Unassigned'."""
    if tutors_df is None or tutors_df.empty or 'Team' not in tutors_df.columns:
        return 'Unassigned'
    row = tutors_df[tutors_df['Tutor_ID'].astype(str).str.strip() == tutor_id_str]
    if row.empty:
        return 'Unassigned'
    val = str(row.iloc[0].get('Team', '')).strip()
    return val if val else 'Unassigned'


def show_admin_panel():
    """Admin dashboard with usage analytics"""
    
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown('<div class="main-header"><h1>📊 Admin Dashboard</h1><p>System Analytics & Usage Statistics</p></div>', unsafe_allow_html=True)
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.tutor_id = None
            st.session_state.admin_mode = False
            st.rerun()
    
    usage_df = load_sheet_data("Usage_Log")
    tutors_df = load_sheet_data("Tutors")
    schedule_df = load_sheet_data("Schedule")
    progress_df = load_sheet_data("Progress_Tracker")
    
    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(["📈 Overview", "👥 Tutor Activity", "⚠️ Daily Alerts", "🏆 Team Leaderboard", "📅 Attendance", "📊 Detailed Logs", "⚙️ System Info"])
    
    with tab1:
        st.markdown("### 📊 Quick Statistics")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            total_tutors = len(tutors_df) if tutors_df is not None and not tutors_df.empty else 0
            st.metric("👥 Total Tutors", total_tutors)
        
        with col2:
            if usage_df is not None and not usage_df.empty:
                unique_users_today = len(usage_df[usage_df['Date'] == datetime.now().strftime('%Y-%m-%d')]['Tutor_ID'].unique())
            else:
                unique_users_today = 0
            st.metric("🟢 Active Today", unique_users_today)
        
        with col3:
            if usage_df is not None and not usage_df.empty:
                topics_today = len(usage_df[
                    (usage_df['Date'] == datetime.now().strftime('%Y-%m-%d')) & 
                    (usage_df['Action'] == 'Topic_Completed')
                ])
            else:
                topics_today = 0
            st.metric("✅ Topics Done Today", topics_today)
        
        with col4:
            if usage_df is not None and not usage_df.empty:
                total_completions = len(usage_df[usage_df['Action'] == 'Topic_Completed'])
            else:
                total_completions = 0
            st.metric("🔢 Total Completions", total_completions)
        
        st.markdown("---")
        
        if usage_df is not None and not usage_df.empty:
            st.markdown("### 📈 Login vs Topic Completion (Last 30 Days)")
            
            usage_df['Date'] = pd.to_datetime(usage_df['Date'])
            daily_activity = usage_df.groupby([usage_df['Date'].dt.date, 'Action']).size().unstack(fill_value=0)
            
            chart_data = pd.DataFrame()
            if 'Login' in daily_activity.columns:
                chart_data['Logins'] = daily_activity['Login']
            if 'Topic_Completed' in daily_activity.columns:
                chart_data['Topics Completed'] = daily_activity['Topic_Completed']
            
            if not chart_data.empty:
                st.line_chart(chart_data)
        else:
            st.info("No usage data available yet.")
    
    with tab2:
        st.markdown("### 👥 Individual Tutor Activity")
        
        if usage_df is not None and not usage_df.empty and tutors_df is not None and not tutors_df.empty:
            tutor_stats = []
            
            for tutor_id in tutors_df['Tutor_ID'].unique():
                tutor_id_str = str(tutor_id).strip()
                tutor_data = usage_df[usage_df['Tutor_ID'].astype(str).str.strip() == tutor_id_str]
                
                tutor_info = tutors_df[tutors_df['Tutor_ID'].astype(str).str.strip() == tutor_id_str]
                tutor_name = tutor_info.iloc[0].get('Name', tutor_id) if not tutor_info.empty else tutor_id
                
                total_logins = len(tutor_data[tutor_data['Action'] == 'Login'])
                total_completions = len(tutor_data[tutor_data['Action'] == 'Topic_Completed'])
                
                login_data = tutor_data[tutor_data['Action'] == 'Login']
                last_login = login_data['Timestamp'].max() if not login_data.empty else 'Never'
                
                today_str = datetime.now().strftime('%Y-%m-%d')
                today_data = tutor_data[tutor_data['Date'] == today_str]
                logins_today = len(today_data[today_data['Action'] == 'Login'])
                completions_today = len(today_data[today_data['Action'] == 'Topic_Completed'])
                
                classes_today = 0
                if schedule_df is not None and not schedule_df.empty:
                    today_date = datetime.now().date()
                    tutor_schedule = schedule_df[
                        schedule_df['Tutor_ID'].astype(str).str.strip() == tutor_id_str
                    ]
                    for _, row in tutor_schedule.iterrows():
                        class_date = parse_date(str(row['Date']))
                        if class_date and class_date == today_date:
                            classes_today += 1
                
                tutor_stats.append({
                    'Tutor_ID': tutor_id,
                    'Name': tutor_name,
                    'Total Logins': total_logins,
                    'Total Completions': total_completions,
                    'Last Login': last_login,
                    'Classes Today': classes_today,
                    'Logins Today': logins_today,
                    'Completed Today': completions_today
                })
            
            stats_df = pd.DataFrame(tutor_stats)
            stats_df = stats_df.sort_values('Total Completions', ascending=False)
            
            st.dataframe(stats_df, use_container_width=True, hide_index=True)
        else:
            st.info("No activity data available yet.")
    
    with tab3:
        st.markdown("### ⚠️ Daily Alerts — Topics & Memos")
        st.info("For each tutor with classes today: tracks both topic completions and memo submissions")

        if schedule_df is not None and not schedule_df.empty:
            today_date = datetime.now().date()
            today_str = datetime.now().strftime('%Y-%m-%d')

            today_classes = []
            for _, row in schedule_df.iterrows():
                class_date = parse_date(str(row['Date']))
                if class_date and class_date == today_date:
                    today_classes.append(row)

            today_classes_df = pd.DataFrame(today_classes) if today_classes else pd.DataFrame()

            if not today_classes_df.empty:
                alerts = []

                for tutor_id in today_classes_df['Tutor_ID'].unique():
                    tutor_id_str = str(tutor_id).strip()

                    tutor_info = tutors_df[tutors_df['Tutor_ID'].astype(str).str.strip() == tutor_id_str] if tutors_df is not None and not tutors_df.empty else pd.DataFrame()
                    tutor_name = tutor_info.iloc[0].get('Name', tutor_id) if not tutor_info.empty and 'Name' in tutor_info.columns else tutor_id
                    team = get_team_for_tutor(tutor_id_str, tutors_df)

                    tutor_classes = today_classes_df[today_classes_df['Tutor_ID'].astype(str).str.strip() == tutor_id_str]
                    num_classes = len(tutor_classes)

                    # Topic completions from Usage_Log
                    if usage_df is not None and not usage_df.empty:
                        completions = usage_df[
                            (usage_df['Tutor_ID'].astype(str).str.strip() == tutor_id_str) &
                            (usage_df['Date'] == today_str) &
                            (usage_df['Action'] == 'Topic_Completed')
                        ]
                        num_topics_done = len(completions)
                    else:
                        num_topics_done = 0

                    # Memo tracking — count today's classes that have a non-empty Tutor_Memo
                    num_memos_done = 0
                    for _, cls_row in tutor_classes.iterrows():
                        memo_val = str(cls_row.get('Tutor_Memo', '')).strip()
                        if memo_val and memo_val.lower() not in ('nan', 'none', ''):
                            num_memos_done += 1

                    topics_pending = max(0, num_classes - num_topics_done)
                    memos_pending = max(0, num_classes - num_memos_done)

                    # Overall status
                    if topics_pending == 0 and memos_pending == 0 and num_classes > 0:
                        overall = "✅ Complete"
                        flag = "🟢"
                    elif topics_pending > 0 and memos_pending > 0:
                        overall = "⚠️ Both Pending"
                        flag = "🔴"
                    elif topics_pending > 0:
                        overall = "⚠️ Topics Pending"
                        flag = "🟠"
                    elif memos_pending > 0:
                        overall = "📝 Memo Pending"
                        flag = "🟡"
                    else:
                        overall = "➖ No Classes"
                        flag = "⚪"

                    alerts.append({
                        'Flag': flag,
                        'Tutor': tutor_name,
                        'Team': team,
                        'Classes Today': num_classes,
                        'Topics Done': num_topics_done,
                        'Topics Pending': topics_pending,
                        'Memos Done': num_memos_done,
                        'Memos Pending': memos_pending,
                        'Status': overall
                    })

                alerts_df = pd.DataFrame(alerts)
                alerts_df = alerts_df.sort_values(['Topics Pending', 'Memos Pending'], ascending=False)

                st.dataframe(alerts_df, use_container_width=True, hide_index=True)

                # Summary counts
                c1, c2, c3 = st.columns(3)
                with c1:
                    n = len(alerts_df[alerts_df['Topics Pending'] > 0])
                    if n:
                        st.error(f"⚠️ {n} tutor(s) have pending topics")
                    else:
                        st.success("✅ All topics marked")
                with c2:
                    n = len(alerts_df[alerts_df['Memos Pending'] > 0])
                    if n:
                        st.warning(f"📝 {n} tutor(s) have missing memos")
                    else:
                        st.success("✅ All memos submitted")
                with c3:
                    n = len(alerts_df[alerts_df['Status'] == '✅ Complete'])
                    st.info(f"🟢 {n} / {len(alerts_df)} tutors fully complete")
            else:
                st.info("No classes scheduled for today")
        else:
            st.info("No schedule data available")

    with tab4:
        st.markdown("### 🏆 Team Leaderboard")

        TEAMS = ['Ashish', 'Nishan', 'Himanshu', 'Tejas']

        if tutors_df is None or tutors_df.empty:
            st.warning("No tutor data available")
        elif 'Team' not in tutors_df.columns:
            st.error("❌ 'Team' column not found in Tutors sheet. Please add a 'Team' column with values: Ashish / Nishan / Himanshu / Tejas")
        else:
            # Date range selector
            from datetime import timedelta
            col1, col2 = st.columns(2)
            with col1:
                lb_days = st.selectbox("Period", ["Today", "Last 7 days", "Last 30 days", "All time"], index=1)
            
            if lb_days == "Today":
                date_cutoff = datetime.now().date()
            elif lb_days == "Last 7 days":
                date_cutoff = datetime.now().date() - timedelta(days=7)
            elif lb_days == "Last 30 days":
                date_cutoff = datetime.now().date() - timedelta(days=30)
            else:
                date_cutoff = None  # All time

            team_stats = []

            for team_name in TEAMS:
                # Tutors in this team
                team_tutors = tutors_df[tutors_df['Team'].astype(str).str.strip() == team_name]
                num_tutors = len(team_tutors)
                if num_tutors == 0:
                    team_stats.append({
                        'Team': team_name, 'Tutors': 0,
                        'Total Classes': 0, 'Topics Marked': 0, 'Memos Written': 0,
                        'Topic %': 0.0, 'Memo %': 0.0, 'Engagement Score': 0.0
                    })
                    continue

                team_tutor_ids = set(team_tutors['Tutor_ID'].astype(str).str.strip().tolist())

                # Filter schedule to this team's tutors + date range
                if schedule_df is not None and not schedule_df.empty:
                    team_schedule = schedule_df[
                        schedule_df['Tutor_ID'].astype(str).str.strip().isin(team_tutor_ids)
                    ].copy()

                    if date_cutoff:
                        def in_range(d):
                            parsed = parse_date(str(d))
                            return parsed is not None and parsed >= date_cutoff
                        team_schedule = team_schedule[team_schedule['Date'].apply(in_range)]

                    total_classes = len(team_schedule)

                    # Memos: count rows with non-empty Tutor_Memo
                    memos_written = 0
                    for _, r in team_schedule.iterrows():
                        memo_val = str(r.get('Tutor_Memo', '')).strip()
                        if memo_val and memo_val.lower() not in ('nan', 'none', ''):
                            memos_written += 1
                else:
                    total_classes = 0
                    memos_written = 0

                # Topics: from Usage_Log
                if usage_df is not None and not usage_df.empty:
                    team_usage = usage_df[
                        usage_df['Tutor_ID'].astype(str).str.strip().isin(team_tutor_ids) &
                        (usage_df['Action'] == 'Topic_Completed')
                    ]
                    if date_cutoff:
                        try:
                            team_usage = team_usage[
                                pd.to_datetime(team_usage['Date'], errors='coerce').dt.date >= date_cutoff
                            ]
                        except Exception:
                            pass
                    topics_marked = len(team_usage)
                else:
                    topics_marked = 0

                # Logins: unique tutors who logged in during period
                if usage_df is not None and not usage_df.empty:
                    login_data = usage_df[
                        usage_df['Tutor_ID'].astype(str).str.strip().isin(team_tutor_ids) &
                        (usage_df['Action'] == 'Login')
                    ]
                    if date_cutoff:
                        try:
                            login_data = login_data[
                                pd.to_datetime(login_data['Date'], errors='coerce').dt.date >= date_cutoff
                            ]
                        except Exception:
                            pass
                    active_tutors = login_data['Tutor_ID'].nunique()
                else:
                    active_tutors = 0

                topic_pct = round((topics_marked / total_classes * 100), 1) if total_classes > 0 else 0.0
                memo_pct = round((memos_written / total_classes * 100), 1) if total_classes > 0 else 0.0
                # Engagement score = average of topic % and memo %
                engagement = round((topic_pct + memo_pct) / 2, 1)

                team_stats.append({
                    'Team': team_name,
                    'Tutors': num_tutors,
                    'Active Tutors': active_tutors,
                    'Total Classes': total_classes,
                    'Topics Marked': topics_marked,
                    'Memos Written': memos_written,
                    'Topic %': topic_pct,
                    'Memo %': memo_pct,
                    'Engagement Score': engagement
                })

            team_df = pd.DataFrame(team_stats).sort_values('Engagement Score', ascending=False).reset_index(drop=True)
            team_df.insert(0, 'Rank', ['🥇', '🥈', '🥉', '4️⃣'][:len(team_df)])

            st.markdown("#### Overall Team Rankings")
            st.dataframe(team_df, use_container_width=True, hide_index=True)

            st.markdown("#### 📊 Engagement Score by Team")
            chart_df = team_df.set_index('Team')[['Topic %', 'Memo %']].copy()
            st.bar_chart(chart_df)

            # Individual breakdown per team
            st.markdown("---")
            st.markdown("#### 👤 Per-Tutor Breakdown by Team")
            for team_name in TEAMS:
                with st.expander(f"Team {team_name}"):
                    team_tutors = tutors_df[tutors_df['Team'].astype(str).str.strip() == team_name]
                    if team_tutors.empty:
                        st.info("No tutors assigned to this team")
                        continue
                    rows = []
                    for _, tr in team_tutors.iterrows():
                        tid = str(tr['Tutor_ID']).strip()
                        tname = str(tr.get('Name', tid)).strip()

                        # Classes in period
                        if schedule_df is not None and not schedule_df.empty:
                            t_sched = schedule_df[schedule_df['Tutor_ID'].astype(str).str.strip() == tid].copy()
                            if date_cutoff:
                                t_sched = t_sched[t_sched['Date'].apply(
                                    lambda d: False if parse_date(str(d)) is None else parse_date(str(d)) >= date_cutoff
                                )]
                            t_classes = len(t_sched)
                            t_memos = sum(1 for _, r in t_sched.iterrows()
                                          if str(r.get('Tutor_Memo', '')).strip() not in ('', 'nan', 'none', 'None'))
                        else:
                            t_classes = 0
                            t_memos = 0

                        # Topics
                        if usage_df is not None and not usage_df.empty:
                            t_topics = usage_df[
                                (usage_df['Tutor_ID'].astype(str).str.strip() == tid) &
                                (usage_df['Action'] == 'Topic_Completed')
                            ]
                            if date_cutoff:
                                try:
                                    t_topics = t_topics[
                                        pd.to_datetime(t_topics['Date'], errors='coerce').dt.date >= date_cutoff
                                    ]
                                except Exception:
                                    pass
                            t_topics_count = len(t_topics)
                        else:
                            t_topics_count = 0

                        rows.append({
                            'Name': tname,
                            'Classes': t_classes,
                            'Topics Marked': t_topics_count,
                            'Memos Written': t_memos,
                            'Topic %': round(t_topics_count / t_classes * 100, 1) if t_classes else 0,
                            'Memo %': round(t_memos / t_classes * 100, 1) if t_classes else 0,
                        })
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    with tab5:
        st.markdown("### 📅 Tutor Attendance — Classes Completed Per Month")
        st.info("A class counts as **completed** only when the tutor has BOTH marked a topic done AND written a memo for that class.")

        if schedule_df is None or schedule_df.empty:
            st.warning("No schedule data available")
        elif tutors_df is None or tutors_df.empty:
            st.warning("No tutor data available")
        else:
            from datetime import timedelta

            # Build attendance data: for every past/today class, check topic + memo
            # "Done" = Tutor_Memo is filled AND at least one topic was marked for that student on that date
            # We use Usage_Log Topic_Completed entries matched by date + student

            # Get all unique months in schedule
            all_months = set()
            for _, row in schedule_df.iterrows():
                d = parse_date(str(row.get('Date', '')))
                if d:
                    all_months.add((d.year, d.month))
            all_months = sorted(all_months, reverse=True)

            if not all_months:
                st.warning("No valid dates found in Schedule")
            else:
                # Month selector
                month_labels = [f"{datetime(y, m, 1).strftime('%B %Y')}" for y, m in all_months]
                selected_label = st.selectbox("Select Month", month_labels, index=0)
                sel_idx = month_labels.index(selected_label)
                sel_year, sel_month = all_months[sel_idx]

                # Filter schedule to selected month
                def in_selected_month(d_str):
                    d = parse_date(str(d_str))
                    return d is not None and d.year == sel_year and d.month == sel_month

                month_schedule = schedule_df[schedule_df['Date'].apply(in_selected_month)].copy()

                if month_schedule.empty:
                    st.info(f"No classes scheduled in {selected_label}")
                else:
                    # Build per-tutor attendance rows
                    attendance_rows = []

                    for tutor_id in sorted(month_schedule['Tutor_ID'].astype(str).str.strip().unique()):
                        tutor_info = tutors_df[tutors_df['Tutor_ID'].astype(str).str.strip() == tutor_id]
                        tutor_name = str(tutor_info.iloc[0].get('Name', tutor_id)).strip() if not tutor_info.empty else tutor_id
                        team = get_team_for_tutor(tutor_id, tutors_df)

                        tutor_month_classes = month_schedule[
                            month_schedule['Tutor_ID'].astype(str).str.strip() == tutor_id
                        ]

                        total = len(tutor_month_classes)
                        done = 0        # both topic + memo
                        memo_only = 0   # memo but no topic logged
                        topic_only = 0  # topic logged but no memo
                        neither = 0     # nothing done

                        for _, cls in tutor_month_classes.iterrows():
                            cls_date_str = str(cls.get('Date', '')).strip()
                            cls_date = parse_date(cls_date_str)
                            student_id_cls = str(cls.get('Student_ID', '')).strip()

                            has_memo = str(cls.get('Tutor_Memo', '')).strip() not in ('', 'nan', 'none', 'None')

                            # Check if a topic was completed for this student by this tutor on/around this date
                            has_topic = False
                            if usage_df is not None and not usage_df.empty and cls_date:
                                cls_date_fmt = cls_date.strftime('%Y-%m-%d')
                                topic_logs = usage_df[
                                    (usage_df['Tutor_ID'].astype(str).str.strip() == tutor_id) &
                                    (usage_df['Action'] == 'Topic_Completed') &
                                    (usage_df['Date'].astype(str).str.strip() == cls_date_fmt)
                                ]
                                # Check details field for student ID match
                                if not topic_logs.empty:
                                    for _, tl in topic_logs.iterrows():
                                        details = str(tl.get('Details', '')).lower()
                                        if student_id_cls.lower() in details:
                                            has_topic = True
                                            break
                                    if not has_topic:
                                        # If details don't match, count any topic completion that day as valid
                                        has_topic = True

                            if has_memo and has_topic:
                                done += 1
                            elif has_memo and not has_topic:
                                memo_only += 1
                            elif has_topic and not has_memo:
                                topic_only += 1
                            else:
                                neither += 1

                        pct = round(done / total * 100, 1) if total > 0 else 0.0

                        attendance_rows.append({
                            'Tutor': tutor_name,
                            'Team': team,
                            'Total Classes': total,
                            '✅ Fully Done': done,
                            '📝 Memo Only': memo_only,
                            '📚 Topic Only': topic_only,
                            '❌ Neither': neither,
                            'Completion %': pct
                        })

                    att_df = pd.DataFrame(attendance_rows).sort_values('Completion %', ascending=False)

                    # Summary metrics
                    c1, c2, c3, c4 = st.columns(4)
                    total_classes_month = att_df['Total Classes'].sum()
                    total_done_month = att_df['✅ Fully Done'].sum()
                    with c1:
                        st.metric("📅 Total Classes", int(total_classes_month))
                    with c2:
                        st.metric("✅ Fully Completed", int(total_done_month))
                    with c3:
                        pct_overall = round(total_done_month / total_classes_month * 100, 1) if total_classes_month > 0 else 0
                        st.metric("📊 Overall %", f"{pct_overall}%")
                    with c4:
                        perfect = len(att_df[att_df['Completion %'] == 100])
                        st.metric("🌟 Tutors at 100%", perfect)

                    st.markdown("---")
                    st.dataframe(att_df, use_container_width=True, hide_index=True)

                    # Per-team summary for the month
                    st.markdown("#### By Team")
                    if 'Team' in att_df.columns:
                        team_att = att_df.groupby('Team').agg(
                            Tutors=('Tutor', 'count'),
                            Total_Classes=('Total Classes', 'sum'),
                            Done=('✅ Fully Done', 'sum')
                        ).reset_index()
                        team_att['Completion %'] = (team_att['Done'] / team_att['Total_Classes'] * 100).round(1).fillna(0)
                        team_att = team_att.sort_values('Completion %', ascending=False)
                        st.dataframe(team_att, use_container_width=True, hide_index=True)

                    # Download
                    csv = att_df.to_csv(index=False)
                    st.download_button(
                        label="📥 Download Attendance CSV",
                        data=csv,
                        file_name=f"attendance_{selected_label.replace(' ', '_')}.csv",
                        mime="text/csv"
                    )

    with tab6:
        st.markdown("### 📋 Detailed Login Logs")
        
        if usage_df is not None and not usage_df.empty:
            col1, col2 = st.columns(2)
            with col1:
                tutor_filter = st.multiselect(
                    "Filter by Tutor",
                    options=usage_df['Tutor_ID'].unique(),
                    default=None
                )
            
            with col2:
                days_back = st.slider("Show last N days", 1, 90, 30)
            
            filtered_df = usage_df.copy()
            
            if tutor_filter:
                filtered_df = filtered_df[filtered_df['Tutor_ID'].isin(tutor_filter)]
            
            from datetime import timedelta
            date_threshold = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
            filtered_df = filtered_df[filtered_df['Date'] >= date_threshold]
            filtered_df = filtered_df.sort_values('Timestamp', ascending=False)
            
            st.dataframe(filtered_df, use_container_width=True, hide_index=True)
            
            csv = filtered_df.to_csv(index=False)
            st.download_button(
                label="📥 Download as CSV",
                data=csv,
                file_name=f"usage_logs_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )
        else:
            st.info("No logs available yet.")
    
    with tab7:
        st.markdown("### ⚙️ System Configuration")
        
        st.markdown("**Google Sheets Configuration:**")
        st.code(f"Spreadsheet ID: {st.secrets['spreadsheet_id']}")
        
        st.markdown("**Available Sheets:**")
        try:
            client = get_google_sheets_client()
            spreadsheet = client.open_by_key(st.secrets["spreadsheet_id"])
            all_sheets = [ws.title for ws in spreadsheet.worksheets()]
            st.write(all_sheets)
        except Exception as e:
            st.error(f"Error accessing sheets: {str(e)}")
        
        st.markdown("**Total Records:**")
        if tutors_df is not None:
            st.write(f"- Tutors: {len(tutors_df)}")
        if schedule_df is not None:
            st.write(f"- Schedule entries: {len(schedule_df)}")
        if usage_df is not None:
            st.write(f"- Usage logs: {len(usage_df)}")
        if progress_df is not None:
            st.write(f"- Progress records: {len(progress_df)}")

# Student Plan View
def show_student_plan():
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        if st.button("← Back to Dashboard"):
            st.session_state.current_view = 'dashboard'
            st.session_state.locally_completed = set()
            load_sheet_data.clear()
            st.rerun()
    
    with col2:
        if st.button("🔄 Refresh", use_container_width=True):
            load_sheet_data.clear()
            st.cache_data.clear()
            st.rerun()
    
    with col3:
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.tutor_id = None
            st.rerun()
    
    student = st.session_state.selected_student
    
    st.markdown(f'<div class="main-header"><h1>{student["name"]}</h1><p>Subject: {student["subject"]}</p></div>', unsafe_allow_html=True)
    
    # subject comes directly from Schedule sheet's Subject column for this class
    # This ensures tutor only sees topics for the subject they are teaching
    class_subject = student.get('subject', '').strip()
    if not class_subject:
        st.error("⚠️ No Subject found for this class in the Schedule sheet. Please add a 'Subject' column to your Schedule sheet.")
        return

    plan_df = get_student_plan(student['id'], subject_filter=class_subject)
    
    
    if plan_df is None or (isinstance(plan_df, pd.DataFrame) and plan_df.empty):
        st.warning("⚠️ No learning plan found for this student")
        st.info("""
        **Possible reasons:**
        
        1. Student needs Grade and Subject filled in Students sheet
        2. Matching topics must exist in Curriculum_Library for that Grade + Subject
        3. Check that column names match exactly (case-sensitive)
        
        **Quick Fix:**
        - Open Students sheet
        - Make sure this student has Grade and Subject filled in
        - Open Curriculum_Library sheet  
        - Verify topics exist for that Grade + Subject
        """)
        return
    
    # Count completed: sheet says so OR marked this session
    locally_done = st.session_state.get('locally_completed', set())
    completed = sum(
        1 for _, r in plan_df.iterrows()
        if r['status'] == 'Completed' or r['planId'] in locally_done
    )
    pending = len(plan_df) - completed

    col1, col2 = st.columns(2)
    with col1:
        st.metric("✅ Completed", completed)
    with col2:
        st.metric("⏳ Pending", pending)
    
    st.markdown("---")

    st.markdown("### 📝 Learning Topics")
    
    for idx, topic in plan_df.iterrows():
        plan_id = topic['planId']

        # A topic is green if the sheet says so OR if we just marked it this session
        is_completed = (topic['status'] == 'Completed') or (plan_id in st.session_state.locally_completed)
        card_class = "topic-card completed" if is_completed else "topic-card"

        st.markdown(f'<div class="{card_class}">', unsafe_allow_html=True)

        col1, col2 = st.columns([4, 1])

        with col1:
            st.markdown(f"**{topic.get('subUnitName', 'Unknown Topic')}**")
            if pd.notna(topic.get('unitName')) and topic.get('unitName'):
                st.caption(f"Unit: {topic['unitName']}")
            if pd.notna(topic.get('contentLink')) and topic.get('contentLink'):
                st.markdown(f"[📎 View Content]({topic['contentLink']})")

        with col2:
            if is_completed:
                st.success("✓ Done")
                if topic.get('completedBy') and topic['completedBy'] not in ('', 'nan'):
                    st.caption(f"By: {topic['completedBy']}")
                elif plan_id in st.session_state.locally_completed:
                    st.caption(f"By: {st.session_state.tutor_id}")
                if topic.get('dateCompleted') and topic['dateCompleted'] not in ('', 'nan'):
                    st.caption(f"{topic['dateCompleted']}")
                elif plan_id in st.session_state.locally_completed:
                    st.caption(datetime.now().strftime('%d/%m/%Y'))
            else:
                if st.button("Mark Done", key=f"complete_{plan_id.replace('|||', '_')}", use_container_width=True):
                    with st.spinner('Saving to sheet...'):
                        success, message = mark_topic_complete(plan_id, st.session_state.tutor_id)
                    if success:
                        st.session_state.locally_completed.add(plan_id)
                        st.cache_data.clear()
                        load_sheet_data.clear()
                        st.toast(f"✅ {message}", icon="✅")
                        st.rerun()
                    else:
                        st.error(f"❌ Save failed: {message}")
                        st.error(f"Plan ID: {plan_id}")

        st.markdown('</div>', unsafe_allow_html=True)

# Main App
def main():
    if not st.session_state.logged_in:
        if st.session_state.admin_mode:
            show_admin_login()
        else:
            show_login()
    else:
        if st.session_state.tutor_id == 'ADMIN':
            show_admin_panel()
        else:
            if st.session_state.current_view == 'dashboard':
                show_dashboard()
            elif st.session_state.current_view == 'student':
                show_student_plan()

if __name__ == "__main__":
    main()

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

# Google Sheets connection - NOT cached so tokens never go stale
def get_google_sheets_client():
    """Connect to Google Sheets using service account credentials."""
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

@st.cache_data(ttl=60)
def load_sheet_data(sheet_name):
    """Load data from a specific sheet"""
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
                st.error(f"Sheet '{sheet_name}' not found. Available sheets: {', '.join(all_sheets)}")
                return None
        
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        df.columns = df.columns.str.strip()
        
        return df
    except Exception as e:
        st.error(f"Error loading {sheet_name}: {str(e)}")
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
        student_map = dict(zip(
            students_df['Student_ID'].astype(str).str.strip(), 
            students_df['Student_Name'].astype(str).str.strip()
        ))
        tutor_classes['Student_Name'] = tutor_classes['Student_ID'].astype(str).str.strip().map(student_map)
    
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

def get_student_plan(student_id, subject_filter=None):
    """Get learning plan for a specific student - automatically generated from curriculum"""
    try:
        students_df = load_sheet_data("Students ")
        if students_df is None:
            students_df = load_sheet_data("Students")
        
        curriculum_df = load_sheet_data("Curriculum_Library")
        progress_df = load_sheet_data("Progress_Tracker")
        
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
            student_topics = curriculum_df.copy()
        
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
            
            plan_id = f"{student_id}-{student_subject}-{topic_id}"
            
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
    # Parse plan_id: format is StudentID-Subject-TopicID
    parts = plan_id.split('-', 2)
    if len(parts) == 3:
        student_id = parts[0]
        subject = parts[1]
        topic_id = parts[2]
    elif len(parts) == 2:
        student_id = parts[0]
        topic_id = parts[1]
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
        worksheet.append_row([
            str(student_id),
            str(topic_id),
            str(subject),
            str(tutor_id),
            current_date
        ])

        log_topic_completion(tutor_id, plan_id, student_id)
        st.cache_data.clear()
        load_sheet_data.clear()
        return True, "Topic marked as completed!"

    except Exception as e:
        import traceback
        traceback.print_exc()
        error_msg = str(e)
        return False, f"Sheet write failed: {error_msg}"

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
            load_sheet_data.clear()
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
        today_classes = classes_df[classes_df['Date'].apply(lambda x: parse_date(x) == today)]
        
        if today_classes.empty:
            st.info("No classes scheduled for today")
        else:
            st.markdown(f"### 📆 {today.strftime('%A, %B %d, %Y')}")
            for _, cls in today_classes.iterrows():
                show_class_card(cls, f"today_{_}")
    
    with tab2:
        upcoming_classes = classes_df[classes_df['Date'].apply(
            lambda x: parse_date(x) and today < parse_date(x) <= next_7_days
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
        past_classes = classes_df[classes_df['Date'].apply(lambda x: parse_date(x) and parse_date(x) < today)]
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
                    'subject': cls['Subject']
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
    
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📈 Overview", "👥 Tutor Activity", "⚠️ Completion Alerts", "📊 Detailed Logs", "⚙️ System Info"])
    
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
        st.markdown("### ⚠️ Completion Alerts - Tutors with Pending Topics")
        st.info("Shows tutors who had classes today but haven't marked all topics complete yet")
        
        if schedule_df is not None and not schedule_df.empty and usage_df is not None:
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
                    
                    tutor_classes = today_classes_df[today_classes_df['Tutor_ID'].astype(str).str.strip() == tutor_id_str]
                    num_classes = len(tutor_classes)
                    
                    completions = usage_df[
                        (usage_df['Tutor_ID'].astype(str).str.strip() == tutor_id_str) &
                        (usage_df['Date'] == today_str) &
                        (usage_df['Action'] == 'Topic_Completed')
                    ]
                    num_completions = len(completions)
                    
                    pending = num_classes - num_completions
                    
                    if pending > 0:
                        status = "⚠️ Behind"
                        alert_color = "🔴"
                    elif pending == 0 and num_classes > 0:
                        status = "✅ On Track"
                        alert_color = "🟢"
                    else:
                        status = "➖ No Classes"
                        alert_color = "⚪"
                    
                    alerts.append({
                        'Status': alert_color,
                        'Tutor_ID': tutor_id,
                        'Tutor_Name': tutor_name,
                        'Classes Today': num_classes,
                        'Topics Completed': num_completions,
                        'Pending': pending if pending > 0 else 0,
                        'Alert': status
                    })
                
                alerts_df = pd.DataFrame(alerts)
                alerts_df = alerts_df.sort_values('Pending', ascending=False)
                
                st.dataframe(alerts_df, use_container_width=True, hide_index=True)
                
                behind_count = len(alerts_df[alerts_df['Pending'] > 0])
                if behind_count > 0:
                    st.error(f"⚠️ {behind_count} tutor(s) have pending topic completions!")
                else:
                    st.success("✅ All tutors are up to date!")
            else:
                st.info("No classes scheduled for today")
        else:
            st.info("No schedule data available")
    
    with tab4:
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
    
    with tab5:
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
    
    plan_df = get_student_plan(student['id'], subject_filter=student['subject'])
    
    st.caption(f"🔍 Debug: Loading topics for Grade/Subject based on schedule. Subject from class: {student['subject']}")
    
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
    
    completed = len(plan_df[plan_df['status'] == 'Completed'])
    pending = len(plan_df[plan_df['status'] != 'Completed'])
    
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
                if st.button("Mark Done", key=f"complete_{plan_id}", use_container_width=True):
                    with st.spinner('Saving to sheet...'):
                        success, message = mark_topic_complete(plan_id, st.session_state.tutor_id)
                    if success:
                        st.session_state.locally_completed.add(plan_id)
                        st.cache_data.clear()
                        load_sheet_data.clear()
                        st.rerun()
                    else:
                        # Show the real error so it can be diagnosed
                        st.error(f"❌ Save failed: {message}")
                        st.warning(f"Plan ID attempted: {plan_id}")

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

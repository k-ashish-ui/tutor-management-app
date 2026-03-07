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

# Google Sheets connection
@st.cache_resource
def get_google_sheets_client():
    """Connect to Google Sheets using service account credentials"""
    try:
        # Get credentials from Streamlit secrets
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

@st.cache_data(ttl=60)  # Cache for only 1 minute
def load_sheet_data(sheet_name):
    """Load data from a specific sheet"""
    try:
        client = get_google_sheets_client()
        if not client:
            return None
        
        spreadsheet = client.open_by_key(st.secrets["spreadsheet_id"])
        
        # Try to get the worksheet
        try:
            worksheet = spreadsheet.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            # If exact name not found, try to find similar names
            all_sheets = [ws.title for ws in spreadsheet.worksheets()]
            # Try with stripped spaces
            for ws_name in all_sheets:
                if ws_name.strip() == sheet_name.strip():
                    worksheet = spreadsheet.worksheet(ws_name)
                    break
            else:
                st.error(f"Sheet '{sheet_name}' not found. Available sheets: {', '.join(all_sheets)}")
                return None
        
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        
        # Clean column names - strip whitespace
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
    
    # Check if required columns exist
    if 'Tutor_ID' not in tutors_df.columns:
        return False, "Tutors sheet missing 'Tutor_ID' column"
    
    if 'Password' not in tutors_df.columns:
        return False, f"Tutors sheet missing 'Password' column. Found columns: {', '.join(tutors_df.columns)}"
    
    # Find tutor
    tutor = tutors_df[tutors_df['Tutor_ID'].astype(str).str.strip() == str(tutor_id).strip()]
    
    if tutor.empty:
        return False, "Invalid Tutor ID"
    
    # Check password
    stored_password = str(tutor.iloc[0]['Password']).strip()
    if stored_password == str(password).strip():
        tutor_name = tutor.iloc[0].get('Name', tutor_id) if 'Name' in tutor.columns else tutor_id
        
        # Log the login activity
        log_login_activity(tutor_id, str(tutor_name))
        
        return True, str(tutor_name)
    else:
        return False, "Invalid password"

def log_login_activity(tutor_id, tutor_name):
    """Log tutor login activity to Usage_Log sheet"""
    try:
        client = get_google_sheets_client()
        spreadsheet = client.open_by_key(st.secrets["spreadsheet_id"])
        
        # Try to get or create Usage_Log sheet
        try:
            worksheet = spreadsheet.worksheet("Usage_Log")
        except gspread.exceptions.WorksheetNotFound:
            # Create the sheet if it doesn't exist
            worksheet = spreadsheet.add_worksheet(title="Usage_Log", rows="1000", cols="6")
            # Add headers
            worksheet.append_row(['Timestamp', 'Tutor_ID', 'Tutor_Name', 'Action', 'Date', 'Details'])
        
        # Add login entry
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        date_only = datetime.now().strftime('%Y-%m-%d')
        worksheet.append_row([timestamp, tutor_id, tutor_name, 'Login', date_only, ''])
        
    except Exception as e:
        # Don't fail login if logging fails
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
        
        # Get Usage_Log sheet
        try:
            worksheet = spreadsheet.worksheet("Usage_Log")
        except gspread.exceptions.WorksheetNotFound:
            # Create if doesn't exist
            worksheet = spreadsheet.add_worksheet(title="Usage_Log", rows="1000", cols="6")
            worksheet.append_row(['Timestamp', 'Tutor_ID', 'Tutor_Name', 'Action', 'Date', 'Details'])
        
        # Get tutor name from cached data or use ID
        tutor_name = str(tutor_id)
        try:
            tutors_df = load_sheet_data("Tutors")
            if tutors_df is not None and not tutors_df.empty:
                tutor = tutors_df[tutors_df['Tutor_ID'].astype(str).str.strip() == str(tutor_id).strip()]
                if not tutor.empty and 'Name' in tutor.columns:
                    tutor_name = str(tutor.iloc[0]['Name'])
        except Exception as e:
            print(f"Error getting tutor name: {e}")
        
        # Add completion entry
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        date_only = datetime.now().strftime('%Y-%m-%d')
        details = f"Student: {student_id}, Plan: {plan_id}"
        
        # Append the row
        worksheet.append_row([timestamp, str(tutor_id), tutor_name, 'Topic_Completed', date_only, details])
        
        print(f"Successfully logged completion: {tutor_id}, {plan_id}")
        
    except Exception as e:
        # Print error but don't fail the completion
        print(f"Error logging completion: {str(e)}")
        import traceback
        traceback.print_exc()

def authenticate_admin(password):
    """Authenticate admin access"""
    # Get admin password from secrets
    admin_password = st.secrets.get("admin_password", "admin123")
    return password == admin_password

def get_tutor_classes(tutor_id):
    """Get all classes for a specific tutor"""
    schedule_df = load_sheet_data("Schedule")
    
    if schedule_df is None or schedule_df.empty:
        return pd.DataFrame()
    
    # Filter by tutor ID
    tutor_classes = schedule_df[schedule_df['Tutor_ID'].astype(str).str.strip() == str(tutor_id).strip()].copy()
    
    # Get student names - try both "Students " and "Students"
    students_df = load_sheet_data("Students ")
    if students_df is None or students_df.empty:
        students_df = load_sheet_data("Students")
    
    if students_df is not None and not students_df.empty:
        # Clean the student IDs for matching
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
    
    # Try different date formats
    formats = ['%d/%m/%Y', '%Y-%m-%d', '%m/%d/%Y', '%d-%m-%Y']
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except:
            continue
    
    return None

def get_student_plan(student_id):
    """Get learning plan for a specific student"""
    plan_df = load_sheet_data("Student_Plan")
    curriculum_df = load_sheet_data("Curriculum_Library")
    
    if plan_df is None or curriculum_df is None:
        return pd.DataFrame()
    
    # Filter by student - handle string comparison properly
    student_plan = plan_df[plan_df['Student_ID'].astype(str).str.strip() == str(student_id).strip()].copy()
    
    # Join with curriculum to get topic names
    if not curriculum_df.empty:
        curriculum_map = dict(zip(
            curriculum_df['Topic_ID'].astype(str).str.strip(), 
            curriculum_df['Sub_Unit_Name'].astype(str).str.strip()
        ))
        unit_map = dict(zip(
            curriculum_df['Topic_ID'].astype(str).str.strip(), 
            curriculum_df['Unit_Name'].astype(str).str.strip()
        ))
        link_map = dict(zip(
            curriculum_df['Topic_ID'].astype(str).str.strip(), 
            curriculum_df['Textbook_Ref'].astype(str).str.strip()
        ))
        
        student_plan['Sub_Unit_Name'] = student_plan['Topic_ID'].astype(str).str.strip().map(curriculum_map)
        student_plan['Unit_Name'] = student_plan['Topic_ID'].astype(str).str.strip().map(unit_map)
        student_plan['Content_Link'] = student_plan.apply(
            lambda row: row.get('Topic_Content', '') if pd.notna(row.get('Topic_Content')) and str(row.get('Topic_Content')).strip() 
                       else link_map.get(str(row['Topic_ID']).strip(), ''),
            axis=1
        )
    
    return student_plan

def save_tutor_memo(student_id, class_date, memo_text):
    """Save tutor memo to the Schedule sheet"""
    try:
        client = get_google_sheets_client()
        spreadsheet = client.open_by_key(st.secrets["spreadsheet_id"])
        worksheet = spreadsheet.worksheet("Schedule")
        
        # Get all data
        data = worksheet.get_all_records()
        
        # Find the row matching student_id and date
        for idx, row in enumerate(data):
            if (str(row.get('Student_ID')).strip() == str(student_id).strip() and 
                str(row.get('Date')).strip() == str(class_date).strip()):
                
                row_num = idx + 2  # +2 because header is row 1 and index starts at 0
                
                # Find Tutor_Memo column
                headers = worksheet.row_values(1)
                if 'Tutor_Memo' in headers:
                    memo_col = headers.index('Tutor_Memo') + 1
                    worksheet.update_cell(row_num, memo_col, memo_text)
                    
                    # Clear cache
                    st.cache_data.clear()
                    return True, "Memo saved successfully!"
                else:
                    return False, "Tutor_Memo column not found in Schedule sheet"
        
        return False, "Class not found in schedule"
    except Exception as e:
        return False, f"Error saving memo: {str(e)}"

def mark_topic_complete(plan_id, tutor_id):
    """Mark a topic as completed"""
    try:
        client = get_google_sheets_client()
        if not client:
            return False, "Cannot connect to Google Sheets"
            
        spreadsheet = client.open_by_key(st.secrets["spreadsheet_id"])
        worksheet = spreadsheet.worksheet("Student_Plan")
        
        # Get all data
        all_data = worksheet.get_all_values()
        
        if len(all_data) < 2:
            return False, "Student_Plan sheet is empty"
        
        headers = all_data[0]
        data_rows = all_data[1:]
        
        # Find column indices
        try:
            plan_id_col = headers.index('Plan_ID')
            student_id_col = headers.index('Student_ID')
            status_col = headers.index('Status')
            completed_by_col = headers.index('Completed_By')
            date_col = headers.index('Date_Completed')
        except ValueError as e:
            return False, f"Required column not found: {str(e)}"
        
        # Find the row with matching Plan_ID
        student_id = None
        found_row = None
        
        for idx, row in enumerate(data_rows):
            if len(row) > plan_id_col and str(row[plan_id_col]).strip() == str(plan_id).strip():
                found_row = idx + 2  # +2 because: header is row 1, and we're in 0-indexed data_rows
                if len(row) > student_id_col:
                    student_id = row[student_id_col]
                break
        
        if found_row is None:
            return False, f"Plan ID '{plan_id}' not found in Student_Plan sheet"
        
        # Update the cells
        current_date = datetime.now().strftime('%d/%m/%Y')
        
        worksheet.update_cell(found_row, status_col + 1, 'Completed')
        worksheet.update_cell(found_row, completed_by_col + 1, str(tutor_id))
        worksheet.update_cell(found_row, date_col + 1, current_date)
        
        # Log the completion activity
        if student_id:
            log_topic_completion(tutor_id, plan_id, student_id)
        
        # Clear ALL caches to force refresh
        st.cache_data.clear()
        load_sheet_data.clear()
        
        return True, "Topic marked as completed!"
        
    except gspread.exceptions.WorksheetNotFound:
        return False, "Student_Plan sheet not found"
    except Exception as e:
        return False, f"Error updating: {str(e)}"

# Login Page
def show_login():
    st.markdown('<div class="main-header"><h1>📚 Tutor Management System</h1><p>Please login to continue</p></div>', unsafe_allow_html=True)
    
    # Admin access link
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
        
        # Debug section
        with st.expander("🔍 Debug Info (Click if login fails)"):
            if st.button("Check Tutors Sheet"):
                tutors_df = load_sheet_data("Tutors")
                if tutors_df is not None:
                    st.success(f"✅ Tutors sheet found with {len(tutors_df)} rows")
                    st.write("**Columns found:**", list(tutors_df.columns))
                    st.write("**Sample data (first 3 rows):**")
                    st.dataframe(tutors_df.head(3))
                else:
                    st.error("❌ Cannot access Tutors sheet")
        
        st.info("💡 **First time setup required:**\n\n1. Create a 'Tutors' sheet with columns: Tutor_ID, Password, Name\n2. Add your credentials there\n3. Configure Google Sheets API (see deployment guide)")

# Dashboard
def show_dashboard():
    # Show memo dialog if triggered
    if st.session_state.show_memo_dialog:
        show_memo_dialog()
        return
    
    # Header
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
    
    # Load classes
    classes_df = get_tutor_classes(st.session_state.tutor_id)
    
    if classes_df.empty:
        st.warning("No classes found for your Tutor ID")
        return
    
    # Tabs
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
            # Group by date
            for date_val in upcoming_classes['Date'].unique():
                date_obj = parse_date(date_val)
                if date_obj:
                    # Calculate days from today
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
            # Group by date (show recent 30 days)
            recent_past = past_classes.head(50)  # Limit to 50 most recent
            
            for date_val in recent_past['Date'].unique():
                date_obj = parse_date(date_val)
                if date_obj:
                    # Calculate days ago
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
            
            # Show existing memo if present
            if pd.notna(cls.get('Tutor_Memo')) and str(cls.get('Tutor_Memo')).strip():
                st.markdown(f"📝 **Memo:** {cls.get('Tutor_Memo')}")
        
        with col2:
            # Add Memo button
            if st.button("📝 Memo", key=f"memo_{unique_key}", use_container_width=True):
                st.session_state.show_memo_dialog = {
                    'student_id': cls['Student_ID'],
                    'student_name': cls.get('Student_Name', cls['Student_ID']),
                    'date': cls['Date'],
                    'existing_memo': cls.get('Tutor_Memo', '')
                }
                st.rerun()
            
            # View Progress button
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
    
    # Memo text area
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
    
    # Header
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
    
    # Load usage data
    usage_df = load_sheet_data("Usage_Log")
    tutors_df = load_sheet_data("Tutors")
    schedule_df = load_sheet_data("Schedule")
    
    # Tabs
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
                # Topics completed today
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
        
        # Activity comparison chart
        if usage_df is not None and not usage_df.empty:
            st.markdown("### 📈 Login vs Topic Completion (Last 30 Days)")
            
            # Group by date and action
            usage_df['Date'] = pd.to_datetime(usage_df['Date'])
            
            daily_activity = usage_df.groupby([usage_df['Date'].dt.date, 'Action']).size().unstack(fill_value=0)
            
            # Create chart data
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
            # Tutor activity summary
            tutor_stats = []
            
            for tutor_id in tutors_df['Tutor_ID'].unique():
                tutor_id_str = str(tutor_id).strip()
                tutor_data = usage_df[usage_df['Tutor_ID'].astype(str).str.strip() == tutor_id_str]
                
                # Get tutor name
                tutor_info = tutors_df[tutors_df['Tutor_ID'].astype(str).str.strip() == tutor_id_str]
                tutor_name = tutor_info.iloc[0].get('Name', tutor_id) if not tutor_info.empty else tutor_id
                
                # Count logins and completions
                total_logins = len(tutor_data[tutor_data['Action'] == 'Login'])
                total_completions = len(tutor_data[tutor_data['Action'] == 'Topic_Completed'])
                
                # Last login
                login_data = tutor_data[tutor_data['Action'] == 'Login']
                last_login = login_data['Timestamp'].max() if not login_data.empty else 'Never'
                
                # Today's activity
                today_str = datetime.now().strftime('%Y-%m-%d')
                today_data = tutor_data[tutor_data['Date'] == today_str]
                logins_today = len(today_data[today_data['Action'] == 'Login'])
                completions_today = len(today_data[today_data['Action'] == 'Topic_Completed'])
                
                # Classes assigned today
                classes_today = 0
                if schedule_df is not None and not schedule_df.empty:
                    # Try multiple date formats
                    today_date = datetime.now().date()
                    
                    tutor_schedule = schedule_df[
                        schedule_df['Tutor_ID'].astype(str).str.strip() == tutor_id_str
                    ]
                    
                    # Count classes that match today's date
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
            
            st.dataframe(
                stats_df,
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No activity data available yet.")
    
    with tab3:
        st.markdown("### ⚠️ Completion Alerts - Tutors with Pending Topics")
        st.info("Shows tutors who had classes today but haven't marked all topics complete yet")
        
        if schedule_df is not None and not schedule_df.empty and usage_df is not None:
            today_date = datetime.now().date()
            today_str = datetime.now().strftime('%Y-%m-%d')
            
            # Get today's classes using the parse_date function
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
                    
                    # Get tutor name
                    tutor_info = tutors_df[tutors_df['Tutor_ID'].astype(str).str.strip() == tutor_id_str] if tutors_df is not None and not tutors_df.empty else pd.DataFrame()
                    tutor_name = tutor_info.iloc[0].get('Name', tutor_id) if not tutor_info.empty and 'Name' in tutor_info.columns else tutor_id
                    
                    # Count classes today
                    tutor_classes = today_classes_df[today_classes_df['Tutor_ID'].astype(str).str.strip() == tutor_id_str]
                    num_classes = len(tutor_classes)
                    
                    # Count completions today
                    completions = usage_df[
                        (usage_df['Tutor_ID'].astype(str).str.strip() == tutor_id_str) &
                        (usage_df['Date'] == today_str) &
                        (usage_df['Action'] == 'Topic_Completed')
                    ]
                    num_completions = len(completions)
                    
                    # Calculate pending
                    pending = num_classes - num_completions
                    
                    # Alert status
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
                # Sort by pending (highest first)
                alerts_df = alerts_df.sort_values('Pending', ascending=False)
                
                # Show alerts
                st.dataframe(
                    alerts_df,
                    use_container_width=True,
                    hide_index=True
                )
                
                # Summary
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
            # Filters
            col1, col2 = st.columns(2)
            with col1:
                tutor_filter = st.multiselect(
                    "Filter by Tutor",
                    options=usage_df['Tutor_ID'].unique(),
                    default=None
                )
            
            with col2:
                days_back = st.slider("Show last N days", 1, 90, 30)
            
            # Apply filters
            filtered_df = usage_df.copy()
            
            if tutor_filter:
                filtered_df = filtered_df[filtered_df['Tutor_ID'].isin(tutor_filter)]
            
            # Date filter
            from datetime import timedelta
            date_threshold = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
            filtered_df = filtered_df[filtered_df['Date'] >= date_threshold]
            
            # Sort by most recent
            filtered_df = filtered_df.sort_values('Timestamp', ascending=False)
            
            st.dataframe(
                filtered_df,
                use_container_width=True,
                hide_index=True
            )
            
            # Download button
            csv = filtered_df.to_csv(index=False)
            st.download_button(
                label="📥 Download as CSV",
                data=csv,
                file_name=f"usage_logs_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )
        else:
            st.info("No logs available yet.")
    
    with tab4:
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

# Student Plan View
def show_student_plan():
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        if st.button("← Back to Dashboard"):
            st.session_state.current_view = 'dashboard'
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
    
    # Header
    st.markdown(f'<div class="main-header"><h1>{student["name"]}</h1><p>Subject: {student["subject"]}</p></div>', unsafe_allow_html=True)
    
    # Load plan
    plan_df = get_student_plan(student['id'])
    
    if plan_df.empty:
        st.warning("No learning plan found for this student")
        return
    
    # Progress overview
    completed = len(plan_df[plan_df['Status'] == 'Completed'])
    pending = len(plan_df[plan_df['Status'] != 'Completed'])
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("✅ Completed", completed)
    with col2:
        st.metric("⏳ Pending", pending)
    
    st.markdown("---")
    st.markdown("### 📝 Learning Topics")
    
    # Display topics
    for _, topic in plan_df.iterrows():
        is_completed = topic['Status'] == 'Completed'
        card_class = "topic-card completed" if is_completed else "topic-card"
        
        st.markdown(f'<div class="{card_class}">', unsafe_allow_html=True)
        
        col1, col2 = st.columns([4, 1])
        
        with col1:
            st.markdown(f"**{topic.get('Sub_Unit_Name', 'Unknown Topic')}**")
            if pd.notna(topic.get('Unit_Name')):
                st.caption(f"Unit: {topic['Unit_Name']}")
            
            if pd.notna(topic.get('Content_Link')) and topic['Content_Link']:
                st.markdown(f"[📎 View Content]({topic['Content_Link']})")
        
        with col2:
            if is_completed:
                st.success("✓ Done")
                st.caption(f"By: {topic.get('Completed_By', 'N/A')}")
                st.caption(f"{topic.get('Date_Completed', 'N/A')}")
            else:
                if st.button("Mark Done", key=f"complete_{topic['Plan_ID']}", use_container_width=True):
                    with st.spinner('Updating...'):
                        success, message = mark_topic_complete(topic['Plan_ID'], st.session_state.tutor_id)
                        if success:
                            st.success(message)
                            # Force immediate refresh by rerunning
                            st.rerun()
                        else:
                            st.error(message)
        
        st.markdown('</div>', unsafe_allow_html=True)

# Main App
def main():
    if not st.session_state.logged_in:
        # Show admin login if admin mode
        if st.session_state.admin_mode:
            show_admin_login()
        else:
            show_login()
    else:
        # Check if logged in as admin
        if st.session_state.tutor_id == 'ADMIN':
            show_admin_panel()
        else:
            # Regular tutor view
            if st.session_state.current_view == 'dashboard':
                show_dashboard()
            elif st.session_state.current_view == 'student':
                show_student_plan()

if __name__ == "__main__":
    main()

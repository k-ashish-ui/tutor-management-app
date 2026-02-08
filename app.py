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
        return True, str(tutor_name)
    else:
        return False, "Invalid password"

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
        spreadsheet = client.open_by_key(st.secrets["spreadsheet_id"])
        worksheet = spreadsheet.worksheet("Student_Plan")
        
        # Get all data
        data = worksheet.get_all_records()
        
        # Find the row
        for idx, row in enumerate(data):
            if str(row.get('Plan_ID')) == str(plan_id):
                row_num = idx + 2  # +2 because header is row 1 and index starts at 0
                
                # Find column indices
                headers = worksheet.row_values(1)
                status_col = headers.index('Status') + 1
                completed_by_col = headers.index('Completed_By') + 1
                date_col = headers.index('Date_Completed') + 1
                
                # Update the cells
                worksheet.update_cell(row_num, status_col, 'Completed')
                worksheet.update_cell(row_num, completed_by_col, tutor_id)
                worksheet.update_cell(row_num, date_col, datetime.now().strftime('%d/%m/%Y'))
                
                # Clear cache to force refresh
                st.cache_data.clear()
                
                return True, "Topic marked as completed!"
        
        return False, "Plan ID not found"
    except Exception as e:
        return False, f"Error updating: {str(e)}"

# Login Page
def show_login():
    st.markdown('<div class="main-header"><h1>📚 Tutor Management System</h1><p>Please login to continue</p></div>', unsafe_allow_html=True)
    
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

# Student Plan View
def show_student_plan():
    col1, col2 = st.columns([3, 1])
    
    with col1:
        if st.button("← Back to Dashboard"):
            st.session_state.current_view = 'dashboard'
            st.rerun()
    
    with col2:
        if st.button("🔄 Refresh Data", use_container_width=True):
            load_sheet_data.clear()
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
                    success, message = mark_topic_complete(topic['Plan_ID'], st.session_state.tutor_id)
                    if success:
                        st.success(message)
                        st.rerun()
                    else:
                        st.error(message)
        
        st.markdown('</div>', unsafe_allow_html=True)

# Main App
def main():
    if not st.session_state.logged_in:
        show_login()
    else:
        if st.session_state.current_view == 'dashboard':
            show_dashboard()
        elif st.session_state.current_view == 'student':
            show_student_plan()

if __name__ == "__main__":
    main()

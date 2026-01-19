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

@st.cache_data(ttl=300)  # Cache for 5 minutes
def load_sheet_data(sheet_name):
    """Load data from a specific sheet"""
    try:
        client = get_google_sheets_client()
        if not client:
            return None
        
        spreadsheet = client.open_by_key(st.secrets["spreadsheet_id"])
        worksheet = spreadsheet.worksheet(sheet_name)
        data = worksheet.get_all_records()
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"Error loading {sheet_name}: {str(e)}")
        return None

def authenticate_tutor(tutor_id, password):
    """Authenticate tutor with ID and password"""
    tutors_df = load_sheet_data("Tutors")
    
    if tutors_df is None or tutors_df.empty:
        return False, "Cannot access Tutors database"
    
    # Find tutor
    tutor = tutors_df[tutors_df['Tutor_ID'].astype(str) == str(tutor_id)]
    
    if tutor.empty:
        return False, "Invalid Tutor ID"
    
    # Check password
    if str(tutor.iloc[0]['Password']) == str(password):
        tutor_name = tutor.iloc[0].get('Name', tutor_id)
        return True, tutor_name
    else:
        return False, "Invalid password"

def get_tutor_classes(tutor_id):
    """Get all classes for a specific tutor"""
    schedule_df = load_sheet_data("Schedule")
    
    if schedule_df is None or schedule_df.empty:
        return pd.DataFrame()
    
    # Filter by tutor ID
    tutor_classes = schedule_df[schedule_df['Tutor_ID'].astype(str) == str(tutor_id)].copy()
    
    # Get student names
    students_df = load_sheet_data("Students ")
    if students_df is not None and not students_df.empty:
        student_map = dict(zip(students_df['Student_ID'].astype(str), students_df['Student_Name']))
        tutor_classes['Student_Name'] = tutor_classes['Student_ID'].astype(str).map(student_map)
    
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
    
    # Filter by student
    student_plan = plan_df[plan_df['Student_ID'].astype(str) == str(student_id)].copy()
    
    # Join with curriculum to get topic names
    if not curriculum_df.empty:
        curriculum_map = dict(zip(curriculum_df['Topic_ID'].astype(str), curriculum_df['Sub_Unit_Name']))
        unit_map = dict(zip(curriculum_df['Topic_ID'].astype(str), curriculum_df['Unit_Name']))
        link_map = dict(zip(curriculum_df['Topic_ID'].astype(str), curriculum_df['Textbook_Ref']))
        
        student_plan['Sub_Unit_Name'] = student_plan['Topic_ID'].astype(str).map(curriculum_map)
        student_plan['Unit_Name'] = student_plan['Topic_ID'].astype(str).map(unit_map)
        student_plan['Content_Link'] = student_plan.apply(
            lambda row: row.get('Topic_Content', '') or link_map.get(str(row['Topic_ID']), ''),
            axis=1
        )
    
    return student_plan

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
                
                # Clear cache
                load_sheet_data.clear()
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
        st.info("💡 **First time setup required:**\n\n1. Create a 'Tutors' sheet with columns: Tutor_ID, Password, Name\n2. Add your credentials there\n3. Configure Google Sheets API (see deployment guide)")

# Dashboard
def show_dashboard():
    # Header
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown(f'<div class="main-header"><h1>📚 My Classes</h1><p>Welcome back, {st.session_state.tutor_name}!</p></div>', unsafe_allow_html=True)
    with col2:
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
    tab1, tab2 = st.tabs(["📅 Today's Classes", "📚 Past Classes"])
    
    today = date.today()
    
    with tab1:
        today_classes = classes_df[classes_df['Date'].apply(lambda x: parse_date(x) == today)]
        
        if today_classes.empty:
            st.info("No classes scheduled for today")
        else:
            for _, cls in today_classes.iterrows():
                show_class_card(cls)
    
    with tab2:
        past_classes = classes_df[classes_df['Date'].apply(lambda x: parse_date(x) and parse_date(x) < today)]
        past_classes = past_classes.sort_values('Date', ascending=False)
        
        if past_classes.empty:
            st.info("No past classes found")
        else:
            for _, cls in past_classes.iterrows():
                show_class_card(cls)

def show_class_card(cls):
    """Display a class card"""
    with st.container():
        st.markdown('<div class="class-card">', unsafe_allow_html=True)
        
        col1, col2 = st.columns([3, 1])
        
        with col1:
            st.markdown(f"### {cls.get('Student_Name', cls['Student_ID'])}")
            st.markdown(f"📅 **Date:** {cls['Date']} | 🕐 **Time:** {cls.get('Start_Time', 'N/A')}")
            st.markdown(f"📖 **Subject:** {cls['Subject']}")
            st.markdown(f"🆔 **Student ID:** {cls['Student_ID']}")
        
        with col2:
            if st.button("View Progress →", key=f"view_{cls['Student_ID']}_{cls['Date']}", use_container_width=True):
                st.session_state.current_view = 'student'
                st.session_state.selected_student = {
                    'id': cls['Student_ID'],
                    'name': cls.get('Student_Name', cls['Student_ID']),
                    'subject': cls['Subject']
                }
                st.rerun()
        
        st.markdown('</div>', unsafe_allow_html=True)

# Student Plan View
def show_student_plan():
    if st.button("← Back to Dashboard"):
        st.session_state.current_view = 'dashboard'
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

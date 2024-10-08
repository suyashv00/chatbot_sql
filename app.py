from dotenv import load_dotenv  # type: ignore
load_dotenv()

import streamlit as st  # type: ignore
import os
import mysql.connector  # type: ignore
import google.generativeai as genai
import pandas as pd
import io
from streamlit_chat import message as st_message  # For chat-like interface # type: ignore

genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

MAX_DISPLAY_ROWS = 10
table = 60

# Initialize session state for chat history and database connection
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []

if 'db' not in st.session_state:
    st.session_state.db = None  # Lazy initialization of database connection

# Refined SQL query generation prompt
prompt = [
"""
You are an expert SQL query generator for the Chinook database. Your task is to convert natural language questions into precise, efficient SQL queries.

Database Schema:
- Artist: ArtistId, Name
- Album: AlbumId, Title, ArtistId
- Track: TrackId, Name, AlbumId, MediaTypeId, GenreId, Composer, Milliseconds, Bytes, UnitPrice
- Customer: CustomerId, FirstName, LastName, Country, Email
- Invoice: InvoiceId, CustomerId, InvoiceDate, BillingAddress, Total

Guidelines:
1. Analyze the user's question carefully to understand the required data and relationships.
2. Use appropriate JOINs when data from multiple tables is needed.
3. Apply WHERE clauses to filter data effectively.
4. Utilize aggregate functions (COUNT, SUM, AVG, etc.) when summarizing data.
5. Implement ORDER BY for sorting and LIMIT for restricting result sets when appropriate.
6. Use subqueries or CTEs for complex operations if necessary.
7. Ensure all table and column names are correctly referenced.
8. Optimize for performance by avoiding unnecessary operations.

Output:
- Return ONLY the SQL query itself, without any explanations, comments, or formatting.
- Do NOT use backticks, code blocks, or any markdown syntax.
- Ensure the query is syntactically correct and executable in MySQL.

Example:
User: What are the top 5 customers by total purchase amount?
SQL: SELECT c.CustomerId, c.FirstName, c.LastName, SUM(i.Total) AS TotalPurchase FROM Customer c JOIN Invoice i ON c.CustomerId = i.CustomerId GROUP BY c.CustomerId, c.FirstName, c.LastName ORDER BY TotalPurchase DESC LIMIT 5;
"""
]


def get_gemini_response(question, prompt):
    model = genai.GenerativeModel('gemini-pro')
    response = model.generate_content([prompt[0], question])
    return response.text

def read_sql_query(sql, db_connection):
    try:
        cursor = db_connection.cursor()
        cursor.execute(sql)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        return pd.DataFrame(rows, columns=columns)
    
    except mysql.connector.Error as err:
        st.error(f"Error executing SQL query: {err}")
        return pd.DataFrame()  # Return an empty dataframe
    
    finally:
        cursor.close()

# Refined natural language summary generation prompt
def sql_to_natural_language(question, sql_query, results):
    result_sample = results.head(10).to_string()
    prompt = f"""
    You are an expert at interpreting SQL query results and providing clear, concise summaries in natural language. Your task is to explain the query results in a way that's easy for non-technical users to understand.

    Input:
    - User's original question: {question}
    - SQL query used: {sql_query}
    - Query results (sample): {result_sample}

    Guidelines:
    1. Start with a direct answer to the user's question.
    2. Provide context by explaining what data was queried and how.
    3. Highlight key insights or patterns in the data.
    4. If only a sample is shown, mention this and avoid making absolute statements about the entire dataset.
    5. Use simple language and avoid technical jargon.
    6. If relevant, suggest potential follow-up questions or areas for further investigation.

    Output:
    - A clear, concise paragraph summarizing the results.
    - Ensure the summary is directly relevant to the original question.
    - If the results are unexpected or potentially erroneous, note this in your summary.

    Example:
    User Question: What are the top 3 genres by number of tracks?
    SQL Query: SELECT g.Name, COUNT(t.TrackId) AS TrackCount FROM Genre g JOIN Track t ON g.GenreId = t.GenreId GROUP BY g.GenreId, g.Name ORDER BY TrackCount DESC LIMIT 3;
    Results Sample: 
    Name    TrackCount
    0  Rock    1297
    1  Latin   579
    2  Metal   374

    Summary: 
    - The top 3 genres by number of tracks are Rock, Latin, and Metal.
    - Rock is the most represented genre with 1,297 tracks.
    - Latin has 579 tracks, and Metal has 374 tracks.
    - This data indicates a strong dominance of Rock music in the database.
    """

    model = genai.GenerativeModel('gemini-pro')
    response = model.generate_content(prompt)
    
    try:
        return response.text
    except AttributeError:
        return "Unable to generate summary due to an error in response format."

def create_excel_download(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Sheet1')
    output.seek(0)
    return output

def is_token_limit_exceeded(df, table):
    total_cells = len(df) * len(df.columns)
    return total_cells > table

def connect_to_db():
    try:
        if st.session_state.db is None:
            conn = mysql.connector.connect(
                host=os.getenv("DB_HOST", "localhost"),
                user=os.getenv("DB_USER"),
                password=os.getenv("DB_PASSWORD"),
                database=os.getenv("DB_NAME", "Chinook")
            )
            st.session_state.db = conn
        return st.session_state.db
    except mysql.connector.Error as err:
        st.error(f"Error connecting to database: {err}")
        return None

def get_response(question, db_connection, chat_history):
    sql_query = get_gemini_response(question, prompt)
    df_response = read_sql_query(sql_query, db_connection)
    
    if not df_response.empty:
        if is_token_limit_exceeded(df_response, table):           
            excel_file = create_excel_download(df_response)
            st.download_button(
                label="Download Excel File",
                data=excel_file,
                file_name="query_results.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.table(df_response)
        
        natural_language_summary = sql_to_natural_language(question, sql_query, df_response)
        return natural_language_summary
    else:
        return "No results found or error in query execution."

# Display the chat interface
st.set_page_config(page_title="SQL Query Chatbot")
st.header("Gemini SQL Query Chatbot")

# Display previous chat history
for message in st.session_state.chat_history:
    if isinstance(message, dict) and message["sender"] == "AI":
        with st.chat_message("AI"):
            st.markdown(message["content"])
    elif isinstance(message, dict) and message["sender"] == "Human":
        with st.chat_message("Human"):
            st.markdown(message["content"])

with st.sidebar:
    st.header("About")
    st.info(
        "This app allows you to query the Chinook database using natural language. "
        "Simply ask a question, and the AI will generate an SQL query and execute it."
    )
    st.header("Sample Questions")
    st.write("1. How many tracks are there?")
    st.write("2. List all artists and their albums.")
    st.write("3. What are the top 5 bestselling tracks?")
    
# Input for new user query
user_query = st.chat_input("Type a message...")
if user_query is not None and user_query.strip() != "":
    # Append the human message to chat history
    st.session_state.chat_history.append({"sender": "Human", "content": user_query})
    
    # Display the human message
    with st.chat_message("Human"):
        st.markdown(user_query)
    
    # Connect to the database and get the response
    db_connection = connect_to_db()
    if db_connection:
        with st.chat_message("AI"):
            response = get_response(user_query, db_connection, st.session_state.chat_history)
            st.markdown(response)
        
        # Append the AI response to chat history
        st.session_state.chat_history.append({"sender": "AI", "content": response})

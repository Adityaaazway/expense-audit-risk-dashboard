import re
import os
from datetime import datetime
import streamlit as st
import pandas as pd
import plotly.express as px
from google import genai


# =========================================================
# APP CONFIG
# =========================================================
st.set_page_config(page_title="Expense Audit Monitor", layout="wide")

st.markdown("""
<style>
.block-container {
    padding-top: 2rem;
    padding-bottom: 2rem;
    max-width: 1200px;
}

[data-testid="stMetric"] {
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.08);
    padding: 16px;
    border-radius: 18px;
}

.stTextArea textarea,
.stTextInput input,
.stSelectbox div[data-baseweb="select"] > div {
    border-radius: 14px !important;
    border: 1px solid rgba(255,255,255,0.12) !important;
    background-color: rgba(255,255,255,0.03) !important;
}

.stButton > button,
.stDownloadButton > button {
    border-radius: 12px !important;
    border: 1px solid rgba(255,255,255,0.10) !important;
    background: linear-gradient(180deg, #1f2937, #111827);
    color: white !important;
    transition: 0.2s ease-in-out;
}

.stButton > button:hover,
.stDownloadButton > button:hover {
    border-color: rgba(245, 158, 11, 0.6) !important;
    transform: translateY(-1px);
}

div[data-testid="stDataFrame"] {
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 16px;
    overflow: hidden;
}
</style>
""", unsafe_allow_html=True)
# =========================================================
# HELPER FUNCTIONS
# =========================================================
def log_nlq_activity(question, sql_query, status, error_message=""):
    log_file = "nlq_query_log.csv"

    log_row = pd.DataFrame([{
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "question": question,
        "sql_query": sql_query,
        "status": status,
        "error_message": error_message
    }])

    if os.path.exists(log_file):
        existing_log = pd.read_csv(log_file)
        updated_log = pd.concat([existing_log, log_row], ignore_index=True)
        updated_log.to_csv(log_file, index=False)
    else:
        log_row.to_csv(log_file, index=False)


# =========================================================
# HEADER SECTION
# =========================================================
st.write("Streamlit version:", st.__version__)

st.title("Expense Audit Risk Dashboard with Natural Language Querying")
st.caption("Internal Audit & Expense Risk Monitor")


# =========================================================
# DATABASE CONNECTION + DATA LOAD
# =========================================================
conn = st.connection("postgresql", type="sql")

kpi_df = conn.query("SELECT * FROM audit_app.vw_expense_kpi_summary;", ttl=0)
risk_df = conn.query("SELECT * FROM audit_app.vw_risk_summary;", ttl=0)
weekend_df = conn.query("SELECT * FROM audit_app.vw_weekend_expenses LIMIT 500;", ttl=0)


# =========================================================
# LABEL MAPS
# =========================================================
label_map = {
    "risk_level": "Risk Level",
    "transaction_count": "Transaction Count",
    "total_amount": "Total Amount",
    "employee_name": "Employee Name",
    "vendor_name": "Vendor Name",
    "expense_date": "Expense Date",
    "amount": "Amount",
    "expense_id": "Expense ID",
    "category": "Category",
    "payment_method": "Payment Method",
    "expense_type": "Expense Type",
    "weekend_flag": "Weekend Flag",
    "flag_reason": "Flag Reason",
    "total_expenses": "Total Expenses",
    "total_employees": "Total Employees",
    "total_vendors": "Total Vendors",
    "total_expense_amount": "Total Expense Amount"
}

log_label_map = {
    "timestamp": "Timestamp",
    "question": "Question",
    "sql_query": "Generated SQL",
    "status": "Status",
    "error_message": "Error Message"
}


# =========================================================
# FILTER SECTION
# =========================================================
st.sidebar.header("Filters")

if "risk_level" in risk_df.columns:
    selected_risk = st.sidebar.multiselect(
        "Risk Level",
        options=sorted(risk_df["risk_level"].dropna().unique()),
        default=list(sorted(risk_df["risk_level"].dropna().unique()))
    )
    risk_df = risk_df[risk_df["risk_level"].isin(selected_risk)]

if "expense_date" in weekend_df.columns:
    weekend_df["expense_date"] = pd.to_datetime(weekend_df["expense_date"], errors="coerce")

if "vendor_name" in weekend_df.columns:
    selected_vendors = st.sidebar.multiselect(
        "Vendor",
        options=sorted(weekend_df["vendor_name"].dropna().unique()),
        default=list(sorted(weekend_df["vendor_name"].dropna().unique()))
    )
    weekend_df = weekend_df[weekend_df["vendor_name"].isin(selected_vendors)]

if "employee_name" in weekend_df.columns:
    selected_employees = st.sidebar.multiselect(
        "Employee",
        options=sorted(weekend_df["employee_name"].dropna().unique()),
        default=list(sorted(weekend_df["employee_name"].dropna().unique()))
    )
    weekend_df = weekend_df[weekend_df["employee_name"].isin(selected_employees)]

if "expense_date" in weekend_df.columns:
    min_date = weekend_df["expense_date"].min()
    max_date = weekend_df["expense_date"].max()

    if pd.notna(min_date) and pd.notna(max_date):
        selected_date_range = st.sidebar.date_input(
            "Expense Date Range",
            value=(min_date.date(), max_date.date())
        )

        if isinstance(selected_date_range, (list, tuple)) and len(selected_date_range) == 2:
            start_date, end_date_raw = selected_date_range
            start_date = pd.to_datetime(start_date)
            end_date = pd.to_datetime(end_date_raw) + pd.Timedelta(days=1)

            weekend_df = weekend_df[
                (weekend_df["expense_date"] >= start_date) &
                (weekend_df["expense_date"] < end_date)
            ]


# =========================================================
# DISPLAY DATA PREP
# =========================================================
risk_df_display = risk_df.rename(columns=label_map)
weekend_df_display = weekend_df.rename(columns=label_map)


# =========================================================
# KPI SECTION
# =========================================================
if not kpi_df.empty:
    cols = st.columns(min(4, len(kpi_df.columns)))
    currency_columns = {"total_expense_amount", "amount", "total_amount", "expense_amount"}

    for i, col in enumerate(kpi_df.columns[:4]):
        with cols[i]:
            value = kpi_df.at[kpi_df.index[0], col]

            if pd.notna(value):
                if col.lower() in currency_columns:
                    formatted_value = f"₹ {value:,.2f}"
                else:
                    try:
                        formatted_value = f"{int(value):,}"
                    except (ValueError, TypeError):
                        formatted_value = f"{value}"
            else:
                formatted_value = "-"

            st.metric(label_map.get(col, col.replace("_", " ").title()), formatted_value)


# =========================================================
# MAIN TABS SECTION
# =========================================================
tab1, tab2, tab3 = st.tabs(["Risk Overview", "Weekend Expense Review", "Power BI Dashboard"])


# =========================================================
# TAB 1 - RISK OVERVIEW
# =========================================================
with tab1:
    st.subheader("Risk Overview")
    st.dataframe(risk_df_display, use_container_width=True)

    csv_risk = risk_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download Risk Overview CSV",
        csv_risk,
        "risk_overview.csv",
        "text/csv"
    )


# =========================================================
# TAB 2 - WEEKEND EXPENSE REVIEW
# =========================================================
with tab2:
    st.subheader("Weekend Expense Review")

    if "Amount" in weekend_df_display.columns:
        st.dataframe(
            weekend_df_display,
            use_container_width=True,
            column_config={
                "Amount": st.column_config.NumberColumn("Amount", format="₹ %,.2f"),
                "Expense Date": st.column_config.DateColumn("Expense Date", format="YYYY-MM-DD")
            }
        )
    else:
        st.dataframe(
            weekend_df_display,
            use_container_width=True,
            column_config={
                "Expense Date": st.column_config.DateColumn("Expense Date", format="YYYY-MM-DD")
            } if "Expense Date" in weekend_df_display.columns else None
        )

    if "amount" in weekend_df.columns and "employee_name" in weekend_df.columns:
        employee_spend_df = (
            weekend_df.groupby("employee_name", as_index=False)["amount"]
            .sum()
            .sort_values("amount", ascending=False)
            .head(10)
        )

        fig = px.bar(
            employee_spend_df,
            x="employee_name",
            y="amount",
            title="Top Weekend Spend by Employee"
        )
        fig.update_layout(
            xaxis_title="Employee Name",
            yaxis_title="Amount",
            yaxis_tickprefix="₹ ",
            yaxis_tickformat=",.2f"
        )
        st.plotly_chart(fig, use_container_width=True)

    if "expense_date" in weekend_df.columns and "amount" in weekend_df.columns:
        trend_df = weekend_df.copy()

        daily_trend = (
            trend_df.groupby("expense_date", as_index=False)["amount"]
            .sum()
            .sort_values("expense_date")
        )

        trend_fig = px.line(
            daily_trend,
            x="expense_date",
            y="amount",
            title="Weekend Expense Trend Over Time",
            markers=True
        )

        trend_fig.update_layout(
            xaxis_title="Expense Date",
            yaxis_title="Total Weekend Amount",
            yaxis_tickprefix="₹ ",
            yaxis_tickformat=",.2f"
        )

        st.plotly_chart(trend_fig, use_container_width=True)

    if "vendor_name" in weekend_df.columns and "amount" in weekend_df.columns:
        top_vendors = (
            weekend_df.groupby("vendor_name", as_index=False)["amount"]
            .sum()
            .sort_values("amount", ascending=False)
            .head(10)
        )

        vendor_fig = px.bar(
            top_vendors,
            x="vendor_name",
            y="amount",
            title="Top Weekend Vendors by Spend"
        )
        vendor_fig.update_layout(
            xaxis_title="Vendor",
            yaxis_title="Total Spend",
            yaxis_tickprefix="₹ ",
            yaxis_tickformat=",.2f"
        )
        st.plotly_chart(vendor_fig, use_container_width=True)

    csv_weekend = weekend_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download Weekend Review CSV",
        csv_weekend,
        "weekend_expense_review.csv",
        "text/csv"
    )


# =========================================================
# TAB 3 - POWER BI SECTION
# =========================================================
with tab3:
    st.subheader("Power BI Dashboard")

    power_bi_report_link = st.secrets.get("POWER_BI_REPORT_URL", "")

    if power_bi_report_link:
        st.write("Open the live Power BI dashboard in a new tab:")
        st.link_button(
            "Open Power BI Report",
            power_bi_report_link,
            use_container_width=True
        )
    else:
        st.info("Add POWER_BI_REPORT_URL to Streamlit secrets to open the Power BI report from here.")


# =========================================================
# SCHEMA SECTION
# =========================================================
schema_file = "audit_app_schema.csv"

if os.path.exists(schema_file):
    schema_df = pd.read_csv(schema_file)

    grouped_schema = (
        schema_df.groupby(["table_schema", "table_name"])["column_name"]
        .apply(list)
        .reset_index()
    )

    schema_text_parts = []
    for _, row in grouped_schema.iterrows():
        full_view_name = f"{row['table_schema']}.{row['table_name']}"
        columns = "\\n".join([f"   - {col}" for col in row["column_name"]])
        schema_text_parts.append(f"{full_view_name}\\n{columns}")

    schema_context_dynamic = "\\n\\n".join(schema_text_parts)

    allowed_views = {
        f"{row['table_schema']}.{row['table_name']}".lower()
        for _, row in grouped_schema.iterrows()
    }
else:
    schema_df = pd.DataFrame()
    schema_context_dynamic = ""
    allowed_views = set()


# =========================================================
# QUERY HISTORY LOAD
# =========================================================
log_file = "nlq_query_log.csv"

if os.path.exists(log_file):
    nlq_log_df = pd.read_csv(log_file)
else:
    nlq_log_df = pd.DataFrame()


# =========================================================
# QUERY HISTORY SECTION
# =========================================================
with st.expander("NLQ Query History", expanded=False):
    if not nlq_log_df.empty:
        status_counts = nlq_log_df["status"].value_counts()

        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Successful Queries", int(status_counts.get("success", 0)))
        with c2:
            st.metric("Blocked Queries", int(status_counts.get("blocked", 0)))
        with c3:
            st.metric("Failed Queries", int(status_counts.get("failed", 0)))

        recent_log_df = nlq_log_df.sort_values("timestamp", ascending=False).head(10)
        recent_log_df_display = recent_log_df.rename(columns=log_label_map)

        st.dataframe(recent_log_df_display, use_container_width=True)

        csv_log = nlq_log_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download Query History CSV",
            csv_log,
            "nlq_query_log.csv",
            "text/csv"
        )
    else:
        st.info("No NLQ queries logged yet.")


# =========================================================
# NLQ / LLM SECTION
# =========================================================
st.markdown("---")
st.subheader("Ask Questions in Natural Language")

if not schema_context_dynamic:
    st.warning("Schema file not found. NLQ-to-SQL is disabled until audit_app_schema.csv is available.")
else:
    example_questions = [
        "Show weekend expenses above 5000",
        "List top 10 vendors by total amount",
        "Show expenses for a specific employee",
        "Summarize total amount by risk level"
    ]

    selected_example = st.selectbox(
        "Try an example question",
        [""] + example_questions
    )

    question = st.text_area(
        "Ask a question about the expense data",
        value=selected_example if selected_example else "",
        placeholder="Example: Show weekend expenses above 5000"
    )

    if st.button("Generate SQL and Run Query", disabled=not question):
        client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])

        schema_context = f"""
You are generating PostgreSQL SQL for an internal expense audit dashboard.

Your job is to translate business language into accurate SQL using the exact schema and the semantic mappings below.

SCHEMA CONTEXT:
{schema_context_dynamic}

CORE RULES:
- Return only one SQL SELECT query.
- Use only the views and columns listed in the schema context above.
- Do not invent table names, column names, or values.
- Do not generate INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, or TRUNCATE.
- Use PostgreSQL syntax.
- Return only SQL. No explanation. No markdown fences.
- Prefer the most relevant audit_app view for the question.
- If the user asks for "how many employees", use COUNT(DISTINCT employee_name) unless they clearly ask for transaction count.
- If the user asks for employees who spent on something, interpret that as employee-level aggregation unless they explicitly ask for raw rows.
- If the user asks for top, highest, most, largest, or above a threshold, use GROUP BY / ORDER BY / HAVING appropriately.
- If a business concept may appear under different actual values in the data, map the user wording to the closest likely values.
- Do not make text filters too strict when the data may use slightly different wording.
- Prefer ILIKE with multiple business synonyms when filtering categories or expense types.
- If the question is ambiguous, choose the most likely interpretation for an internal expense audit dashboard.

SEMANTIC MAPPINGS:

1) Flight / Air travel expenses
User may mean:
- flight
- flights
- airfare
- airline ticket
- air ticket
- plane ticket
- flight booking
- air travel
- corporate travel
Possible database meanings may include values such as:
- Flight
- Airfare
- Airline
- Air Travel
- Travel - Air
- Air Ticket
- Flight Expense
- Travel
When the user refers to flight-related spend, try matching against category, expense_type, vendor_name, or other relevant text columns using broad semantic matching.

2) Hotel / Stay / Accommodation
User may mean:
- hotel
- stay
- lodging
- accommodation
- room booking
- guest house
Possible values may include:
- Hotel
- Lodging
- Accommodation
- Stay
- Travel - Hotel
- Room Booking

3) Meals / Food / Dining
User may mean:
- food
- meals
- dining
- lunch
- dinner
- breakfast
- restaurant
- catering
Possible values may include:
- Food
- Meals
- Dining
- Restaurant
- Catering
- Hospitality

4) Taxi / Cab / Ground transport
User may mean:
- taxi
- cab
- ride
- uber
- ola
- local transport
- commute
- transport
Possible values may include:
- Taxi
- Cab
- Ride
- Local Transport
- Transport
- Travel - Ground

5) Weekend language
User may mean:
- weekend
- saturday
- sunday
- off day
- non-working day
If a weekend flag exists, use it.
Otherwise, infer from expense_date if needed.

6) Employee count language
If the user says:
- how many employees
- number of employees
- employees who spent
- employee count
Then prefer:
- COUNT(DISTINCT employee_name)
unless they explicitly ask for a list of employees.

7) Threshold language
Interpret these similarly:
- above 5000
- more than 5000
- over 5000
- greater than 5000
- exceeds 5000
Map them to numeric comparison on amount or total_amount as appropriate.

8) Vendor language
User may mean:
- top vendors
- biggest vendors
- most used vendors
- vendor concentration
- vendor risk
Use vendor_name with aggregation by amount or transaction count depending on the question.

9) Risk language
User may mean:
- risky employees
- suspicious expenses
- anomalies
- policy violations
- high risk
Map these to risk_level, flag_reason, or risk-related views when available.

10) Date language
User may mean:
- today
- yesterday
- last week
- last month
- this month
- this quarter
- year to date
Convert to proper SQL date filtering when relevant.

RESULT SHAPE RULES:
- If the user asks "how many", return a count.
- If the user asks "which employees" or "list employees", return employee_name and relevant metrics.
- If the user asks "show expenses", return rows.
- If the user asks "top 10", apply LIMIT 10.
- If the user asks "by vendor", group by vendor_name.
- If the user asks "by employee", group by employee_name.
- If the user asks "by risk level", group by risk_level.
- If the user asks "by category", group by category.

QUERY STRATEGY:
- First infer the business intent.
- Then identify the correct view and columns.
- Then map natural language terms to likely column values.
- Then generate the SQL.
- For text concepts like flight, hotel, meals, taxi, etc., prefer broad semantic matching across relevant text columns if exact values are uncertain.
- Avoid returning zero rows due to overly narrow exact string matching when broader matching is more appropriate.
"""

        prompt = f"""
{schema_context}

User question:
{question}
"""

        try:
            response = client.models.generate_content(
                model="models/gemini-2.5-flash",
                contents=prompt
            )

            sql_query = response.text.strip()
            sql_query = re.sub(r"^```sql\s*", "", sql_query, flags=re.IGNORECASE)
            sql_query = re.sub(r"^```\s*|\s*```$", "", sql_query).strip()

            st.write("Generated SQL:")
            st.code(sql_query, language="sql")

            sql_upper = sql_query.upper()
            blocked_words = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE"]

            referenced_views = set(
                match.lower()
                for match in re.findall(r"(?:from|join)\s+([a-zA-Z0-9_.]+)", sql_query, flags=re.IGNORECASE)
            )

            invalid_views = referenced_views - allowed_views

            if not sql_upper.startswith("SELECT"):
                log_nlq_activity(question, sql_query, "blocked", "Only SELECT queries are allowed.")
                st.error("Blocked: Only SELECT queries are allowed.")
            elif any(word in sql_upper for word in blocked_words):
                log_nlq_activity(question, sql_query, "blocked", "Unsafe SQL detected.")
                st.error("Blocked: Unsafe SQL detected.")
            elif invalid_views:
                error_msg = f"Query references unauthorized views/tables: {', '.join(sorted(invalid_views))}"
                log_nlq_activity(question, sql_query, "blocked", error_msg)
                st.error(f"Blocked: {error_msg}")
            else:
                llm_result_df = conn.query(sql_query, ttl=0)
                log_nlq_activity(question, sql_query, "success", "")
                st.success("Query executed successfully.")

                llm_result_display = llm_result_df.rename(columns=label_map)

                currency_candidate_cols = {
                    "amount",
                    "total_amount",
                    "expense_amount",
                    "total_expense_amount",
                    "spend",
                    "total_spend",
                    "cost"
                }

                date_candidate_cols = {
                    "expense_date"
                }

                column_config = {}

                for col in llm_result_df.columns:
                    display_col = label_map.get(col, col.replace("_", " ").title())

                    if col.lower() in currency_candidate_cols:
                        column_config[display_col] = st.column_config.NumberColumn(
                            display_col,
                            format="₹ %,.2f"
                        )
                    elif col.lower() in date_candidate_cols:
                        column_config[display_col] = st.column_config.DateColumn(
                            display_col,
                            format="YYYY-MM-DD"
                        )

                st.dataframe(
                    llm_result_display,
                    use_container_width=True,
                    column_config=column_config
                )

                csv_llm = llm_result_df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "Download NLQ Result CSV",
                    csv_llm,
                    "nlq_result.csv",
                    "text/csv"
                )

        except Exception as e:
            log_nlq_activity(
                question,
                sql_query if "sql_query" in locals() else "",
                "failed",
                str(e)
            )
            st.error(f"Query failed: {e}")
import os
import sys
from pathlib import Path
PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_DIR))
from utils.database import DatabaseUtil
from utils.llm_pick import pick_llm
from Models.schema import AgentSchema, JudgeSchema
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph import StateGraph, START,END
from IPython.display import display,Image


#  --------------- AI Agent Code -----------------------------------------


def curate_question(state : AgentSchema) -> AgentSchema:
    user_question = state.user_question
    llm=pick_llm('low')
    response = llm.invoke(f"Curate the following question: {user_question}").content
    return {"curated_question": response, "messages": [HumanMessage(content=response)]}
def prompt_query_context(state : AgentSchema)-> AgentSchema :
    curated_question = state.curated_question
    connec_details = {
        "host": os.environ['host'],
        "port": int(os.environ['port']),
        "database": os.environ['database'],
        "user": os.environ['user'],
        "password": os.environ['password'],
    }
    obj = DatabaseUtil(connec_details)
    schema_info = obj.schema_details("public")
    prompt = f"""
    You are an SQL analyst agent. Your task is to convert the user's natural language 
    query into Postgres SQL query that can be executed on the database. You are provided 
    with the user's original query and the schema details of the database, including
    table names, column names, data types, and sample data for each table so that 
    you can understand the structure of the database and generate an accurate SQL query.
    Unless user explicitly asks for specific number of rows, always limit the output to 10 rows.
    Note - Just generate the SQL query without any explanation or additional text because
    this query will be executed directly on the database. So, the output should be SQL
    ready to be executed without any modifications.  
    
    User's Original Query: {curated_question}

    Database Schema Details:
    {schema_info}
    

    """    
    return {"prompt_query_context": prompt}
# generate sql query node
def generate_sql_query(state : AgentSchema)-> AgentSchema:
    prompt = state.prompt_query_context
    llm = pick_llm('medium')
    generated_sql_query = llm.invoke(prompt).content
    return {"generated_sql_query": generated_sql_query}

# is safe node 
def is_safe(state : AgentSchema)-> AgentSchema:
    sql_query = state.generated_sql_query
    llm=pick_llm('medium')
    llm_judge=llm.with_structured_output(JudgeSchema)
    prompt = f"""
    You are an SQL Judge for data security. Your task is to determine whether the SQL query is safe or not. 
    The SQL query should only be used for data retrieval and should not modify the database in any way.
      Neither the SQL query nor the prompt should contain any SQL commands that can modify the database, 
    such as INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE, or any other commands that can change the structure or content of the database. 
    If the SQL query is safe, respond with 'Yes' otherwise respond with 'No'. Additionally, provide comments explaining your decision.
    Here's the SQL query to evaluate:
    {sql_query}
    """
    response = llm_judge.invoke(prompt).model_dump()
    return {"is_safe": response["answer"], "comment": response["comments"]}

# cancelled sql node 
def cancelled_sql(state : AgentSchema)-> AgentSchema:
    comments= state.comment
    return {"final_answer": f"The SQL query was deemed unsafe to execute. Comments from the judge: {comments}"}
# execute sql node
def execute_sql(state : AgentSchema)-> AgentSchema:
    sql_query=state.generated_sql_query
    connec_details = {
        "host": os.environ['host'],
        "port": int(os.environ['port']),
        "database": os.environ['database'],
        "user": os.environ['user'],
        "password": os.environ['password'],
    }
    obj = DatabaseUtil(connec_details)
    execution_result = obj.execute_query(sql_query)
    return {"sql_query_execution_result": execution_result,
            "messages": [AIMessage(content=str(execution_result))]}
# representation node 
def represente_final_answer(state : AgentSchema)-> AgentSchema:
    execution_result = state.sql_query_execution_result
    curated_question = state.curated_question
    llm = pick_llm('low')
    prompt =  f"""
    You are an SQL analyst agent. Your task is to provide a final answer to the user based on the
    execution result of the SQL query and the user's original question. The final answer should be
    concise, clear, and directly address the user's query. Avoid including any SQL code or technical
    details in the final answer. The final answer should be in a user-friendly format that is easy to
    understand. If the execution result is empty or does not provide a clear answer to the user's question, explain this in the final answer. \n
    Here is the execution result: {execution_result} \n
    Here is the user's original question: {curated_question}
    """
    llm_response = llm.invoke(prompt).content
    return {"final_answer": llm_response, "messages": [AIMessage(content=llm_response)]}    
# ------------------------------ Graph Building
sql_agent_graph=StateGraph(AgentSchema)

#nodes
sql_agent_graph.add_node(curate_question,name="curate_question")
sql_agent_graph.add_node(prompt_query_context,name="prompt_query_context")
sql_agent_graph.add_node(generate_sql_query,name="generate_sql_query")
sql_agent_graph.add_node(is_safe,name="is_safe")
sql_agent_graph.add_node(cancelled_sql,name="cancelled_sql")
sql_agent_graph.add_node(execute_sql,name="execute_sql")
sql_agent_graph.add_node(represente_final_answer,name="represente_final_answer")

#Edges
sql_agent_graph.add_edge(START,"curate_question")
sql_agent_graph.add_edge("curate_question","prompt_query_context")
sql_agent_graph.add_edge("prompt_query_context","generate_sql_query")
sql_agent_graph.add_edge("generate_sql_query","is_safe")

#conditional edges based on safety check

def is_safe_condition(state: AgentSchema) -> str:
    is_safe = state.is_safe
    if is_safe.lower() == "yes":
        return "execute_sql"
    else:
        return "cancelled_sql"

sql_agent_graph.add_conditional_edges("is_safe", is_safe_condition, 
                                      {
                                          "execute_sql":"execute_sql",
                                          "cancelled_sql":"cancelled_sql"
                                      })


sql_agent_graph.add_edge("cancelled_sql",END)    
sql_agent_graph.add_edge("execute_sql","represente_final_answer")
sql_agent_graph.add_edge("represente_final_answer",END)

sql_analyst=sql_agent_graph.compile()

if __name__=="__main__":
    #compile graph
    # optional
    sql_analyst=sql_agent_graph.compile()

    img=Image(sql_analyst.get_graph().draw_mermaid_png())

    with open("sql_analyst_graph.png", "wb") as f:
        f.write(img.data)

    input_schema= {
        "messages": [],
        "user_question": "What are the names and emails of users who live in Winnipeg",
        "curated_question": "",
        "prompt_query_context": "",
        "generated_sql_query": "",
        "is_safe": None,
        "comment": "",
        "sql_query_execution_result": "",
        "final_answer": ""
    }    
    #execute graph

    sql_analyst_execute = sql_analyst.invoke(input_schema)

    print("\nRéponse finale :")
    print(sql_analyst_execute["final_answer"])
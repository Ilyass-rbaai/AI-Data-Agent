import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__),'..')))
from utils.llm_pick import pick_llm
from utils.etl_tools import Etl_tools
from Models.schema import RouterSchema , DataAgentSchema
from langchain_core.messages import AIMessage ,HumanMessage,ToolMessage
from langgraph.graph import StateGraph, START, END
from langchain.tools import tool
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage
from agents.etl_analyst import etl_analyst
from agents.sql_analyst import sql_analyst
from IPython.display import display,Image

llm=pick_llm("medium")
llm_router=llm.with_structured_output(RouterSchema)

#---------------------- Data Agent Graph ------------------------------------

def router_node(state: DataAgentSchema):
    message = state.messages[-1].content
    response = llm_router.invoke(message)

    return {"route_response": response.answer}

def elt_node(state: DataAgentSchema):
    response = etl_analyst.invoke({
        "messages": [
            HumanMessage(content=state.messages[-1].content)
        ]
    })

    return {"messages": [response["messages"][-1]]}

def sql_node(state: DataAgentSchema):
    message = state.messages[-1].content
    input_schema ={
            "messages": [],
            "user_question": f"{message}",
            "curated_question": "",
            "prompt_query_context": "",
            "generated_sql_query": "",
            "is_safe": None,
            "comment": "",
            "sql_query_execution_result": "",
            "final_answer": ""
            }
    response = sql_analyst.invoke(input_schema)

    return {
    "messages": [
        AIMessage(content=response["final_answer"])
    ]
    }

data_agent_graph = StateGraph(DataAgentSchema)

data_agent_graph.add_node("router_node",router_node)
data_agent_graph.add_node("etl_node",elt_node)
data_agent_graph.add_node("sql_node",sql_node)

data_agent_graph.add_edge(START,"router_node")

def router_edge(state:DataAgentSchema) -> str :
    if state.route_response == "sql":
        return "sql_node"
    elif state.route_response == "etl":
        return "etl_node"
    else:
        raise ValueError(f"invalid route response {state.route_response}")

data_agent_graph.add_conditional_edges("router_node", router_edge,
                                       {
                                           "sql_node" : "sql_node",
                                           "etl_node" : "etl_node"
                                       })

data_agent_graph.add_edge("etl_node", END)
data_agent_graph.add_edge("sql_node", END)

data_agent =data_agent_graph.compile()

if __name__ == "__main__":
    img=Image(data_agent.get_graph().draw_mermaid_png())
    
    with open("data_agent_graph.png", "wb") as f:
        f.write(img.data)
    

    result = data_agent.invoke({
        "messages": [
            HumanMessage(
                content="I want ro extract the data from the API endpoint 'https://pokeapi.co/api/v2/pokemon' and save it to data/extract folder in a csv file"
            )
        ],
        "route_response": "",
    })

    print(result["messages"][-1].content)
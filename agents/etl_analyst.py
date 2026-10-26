import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__),'..')))
from utils.llm_pick import pick_llm
from utils.etl_tools import Etl_tools
from Models.schema import EtlAgentSchema
from langchain_core.messages import AIMessage ,HumanMessage,ToolMessage
from langgraph.graph import StateGraph, START, END
from langchain.tools import tool
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage


#--------------------etl agent tools --------------------------------
@tool
def extract_load_tool(url:str,output_folder:str,format:str) -> str :

        """
        this tool extract the data from teh API (url) and load it into the 
        desired location.
    
        Args:
        url(str): The api endpoint from whitch to extract data.
        output_folder (str): The folder where the extracted data will be saved.
        outputfolder(str)
    
        Return:
        str : A message indicating the success or failure of the operation.
        """
        etl_tools=Etl_tools()
        return etl_tools.extract_load(url,output_folder,format)    
@tool
def tranform_load_tool(input_file_path:str,output_folder:str,output_format:str,user_question:str) ->str :

        """
        This tool transforms the data from the specified file and loads it into the
        desired location (output_folder).

        Args:
            input_file_path (str): The path to the file containing the data to be transformed.
            output_folder (str): The folder where the transformed data will be saved.
            output_format (str): The format in which to save the transformed data (csv, json, parquet).
        
        Returns:
            str: A message indicating the success or failure of the operation.

        """
        etl_tools=Etl_tools()
        top_3_rows = etl_tools.transform_load_context(input_file_path)
        llm =pick_llm('medium')

        prompt =f"""
            You are a Python Data Analyst who uses Pandas to analyze data. 
            You need to provide only the Pandas Code that will help to perform the right ETL operations on the data stored in the file : {input_file_path}
            as per the user's question. Do not provide any explanation or comments, only
            the code should be provided. The code should be in a format that can be executed 
            in a Python environment with Pandas installed. 
            Don't write anything else than Pandas Code. \n
            
            Create the Pandas Dataframe from the data stored in the file : {input_file_path} and then 
            write the code to transform and save the data at {output_folder} in {output_format} format.
            Create the output folder if it does not exist.
            Here's the user's question: {user_question}\n
            Here's the context of the data you will be analyzing: {top_3_rows}\n
                """
        response = llm.invoke(prompt).content
        pandas_code = response.strip()
        if pandas_code.startswith("```"):
            lines = pandas_code.splitlines()
            if len(lines) < 3 or lines[-1].strip() != "```":
                raise ValueError("Incomplete code block returned by model")
            pandas_code = "\n".join(lines[1:-1])

        results=etl_tools.execute_code(pandas_code)
        if results.startswith("Failed to execute code"):
            raise RuntimeError(results)
        return f"Transformation code completed. Requested destination: {output_folder}; format: {output_format}. Execution result: {results}. Check the output file to verify the transformation."

#toolkit
tools = [extract_load_tool,tranform_load_tool]

llm = pick_llm('medium')
llm_bind = llm.bind_tools(tools)

#--------------------etl agent graph --------------------------------

def llm_node(state:EtlAgentSchema):
        response = llm_bind.invoke([
        SystemMessage(content=(
            "You are a data analyst with tools for extracting, "
            "transforming and saving data. Use the appropriate tools "
            "to fulfill the user's request. Once completed, "
            "report the result and end the conversation."
        )),
        *state.messages,
        ])

        return {"messages": [response]}

def tool_node(state: EtlAgentSchema):
    tools_result = []
    tool_by_name = {tool.name: tool for tool in tools}

    for tool_call in state.messages[-1].tool_calls:
        selected_tool = tool_by_name[tool_call["name"]]
        observation = selected_tool.invoke(tool_call["args"])

        tools_result.append(
            ToolMessage(
                content=str(observation),
                tool_call_id=tool_call["id"],
            )
        )

    return {"messages": tools_result}       

# nodes and edges

etl_analyst_graph = StateGraph(EtlAgentSchema)
etl_analyst_graph.add_node("llm_node", llm_node)
etl_analyst_graph.add_node("tool_node", tool_node)

etl_analyst_graph.add_edge(START, 'llm_node')

def is_tool_call(state: EtlAgentSchema):
    if state.messages[-1].tool_calls:
        return "tool_node"
    return "end"

etl_analyst_graph.add_conditional_edges("llm_node",is_tool_call,
                                        {
                                                "tool_node": "tool_node",
                                                "end": END
                                        }
                                        )
etl_analyst_graph.add_edge("tool_node","llm_node")
etl_analyst = etl_analyst_graph.compile()
if __name__ == "__main__":
        

        from IPython.display import display ,Image
        img=Image(etl_analyst.get_graph().draw_mermaid_png())
        with open("etl_analyst_graph.png","wb") as f:
                f.write(img.data)

       # response = etl_analyst.invoke(
        #        {"messages": [HumanMessage(content = "I want ro extract the data from the API endpoint 'https://pokeapi.co/api/v2/pokemon' and save it to data/extract folder in a csv file")]}
        #)
        response = etl_analyst.invoke(
          {"messages":[HumanMessage(content=f"""
             I want to transform the data stored in the C:\\Users\\HP\\Documents\\AI Data Agent\\data\\extract\\extracted_data.csv' file 
             and save the transformed data in the 'C:\\Users\\HP\\Documents\\AI Data Agent\\data\\transform' folder in the csv format.
             The transformation should filter the data to show venusaur pokemon only.
            """)]}
     )              
        print(response)
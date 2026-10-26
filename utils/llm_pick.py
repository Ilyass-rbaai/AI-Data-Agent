from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
load_dotenv() 
def pick_llm(level):
    """
    Pick the appropriate LLM based on the level of complexity.

    Args:
        level (str): The level of complexity ('simple', 'medium', 'complex').

    Returns:
        str: The name of the selected LLM.
    """
    if level.lower()=='low':
            llm = ChatOpenAI(
            model_name="gpt-6-luna",
            reasoning_effort="none",
        )
    elif level.lower()=='medium':
         llm = ChatOpenAI(
        model_name="gpt-6.1-sol",
        reasoning_effort="low",
    )
    elif level.lower()=='high':
         llm=ChatOpenAI(model_name="gpt-6-astra",reasoning_effort="none",)      
    else :
        raise ValueError(f"Invalid level: {level}.")
    return llm
if __name__=="__main__":
    llm_obj=pick_llm('low')
    print(llm_obj.invoke("what is the capital of usa ?"))
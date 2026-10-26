import os
import requests
import pandas as pd
class Etl_tools:
    def __init__(self):
        pass
    def extract_load(self,url:str,outputfolder:str,format:str):
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
        
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__),'..'))
        outputfolder = os.path.join(project_root,outputfolder)

        try:
            if format not in {"csv", "json", "parquet"}:
                raise ValueError(f"Unsupported output format: {format}")
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and "results" in data:
                records = data["results"]
            elif isinstance(data, list):
                records = data
            else:
                raise ValueError("API response must be a list or contain a results list")
            if not isinstance(records, list):
                raise ValueError("API results must be a list")
            filename = os.path.join(outputfolder,f"extracted_data.{format}")
            os.makedirs(outputfolder,exist_ok=True)
            df = pd.json_normalize(records)
            if format == "csv":
                df.to_csv(filename,index=False)
            elif format == "json":
                df.to_json(filename,orient="records",lines=True)
            elif format == "parquet":
                df.to_parquet(filename,index=False)    
            return f"Data successfully extracted and saved to {filename} ({len(df)} rows)"
        except requests.exceptions.RequestException as e :
            return f"Failed to extract data : {e}"

    def transform_load_context(self,file_path:str):
        """
        This tool transforms the data from the specified file and loads it into the
        desired location (output_folder).

        Args:
            file_path (str): The path to the file containing the data to be transformed.
            output_folder (str): The folder where the transformed data will be saved.
            output_format (str): The format in which to save the transformed data (csv, json, parquet).
        Returns:
            str: A message indicating the success or failure of the operation.
        """        
        file_extension = os.path.splitext(file_path)[1].lower()
        if file_extension == ".csv" :
            df=pd.read_csv(file_path)
        elif file_extension == ".json":
            try:
                df = pd.read_json(file_path)
            except ValueError:
                df = pd.read_json(file_path, lines=True)
        elif file_extension == ".parquet":
            df=pd.read_parquet(file_path)
        else :
            return f"Unsupported file format {file_extension}"
        top_3_rows=str(df.head(3))
        return top_3_rows

    def execute_code(self,code:str):
        """
        This tool executes the provided code and returns the output.

        Args:
            code (str): The code to be executed.
        Returns:
            str: The output of the executed code or an error message if execution fails.
        """
        try:
            exec(code)
            return "Code executed successfully."
        except Exception as e:
            return f"Failed to execute code {e}"

if __name__ =="__main__":        
    obj = Etl_tools()
    path = "C:\\Users\\HP\\Documents\\AI Data Agent\\data\\extract\\extracted_data.csv"
    print(obj.transform_load_context(path))    
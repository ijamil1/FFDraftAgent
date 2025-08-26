import os
import json
import uuid
import subprocess
from threading import Thread
from openai import OpenAI, RateLimitError
import itertools, sys, threading, time
from dotenv import load_dotenv
from datetime import date
import argparse
import requests
from bs4 import BeautifulSoup
import pandas as pd

load_dotenv()

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
today = date.today()
season = today.year
llm_written_files = [] # list of files that the llm has written to the local directory
max_retries = 5
backoff = 5  # seconds
teams = [
    "NYJ",
    "PHI",
    "LAC",
    "DEN",
    "LV",
    "NO",
    "TEN",
    "MIA",
    "CIN",
    "HOU",
    "SEA",
    "TB",
    "CLE",
    "ATL",
    "MIN",
    "IND",
    "CHI",
    "BUF",
    "JAC",
    "KC",
    "CAR",
    "LAR",
    "SF",
    "BAL",
    "DET",
    "ARI",
    "GB",
    "NYG",
    "DAL",
    "WAS",
    "PIT",
    "NE"]

# System prompt (configurable via env var AGENT_SYSTEM_PROMPT)
SYSTEM_PROMPT =  f"You are a fantasy football expert who grounds opinions based on facts and the latest news and projections, and you have taken on the role of a helpful, concise assistant. \
Your goal is to help the user in the upcoming {season} fantasy football season. \
You can run draft simulations given some inputs from the user. \
You can answer questions about the simulation design and intricacies. \
You can help the user prepare for the draft and by answering their questions about the draft and the upcoming NFL season in general by getting the most up-to-date and current news and information from the web as of {today.strftime('%B %d, %Y')}. \
You can save and write files to the local directory. \
Whenever you do use the web, use the best sources for {season} fantasy football data like ESPN, CBS, Yahoo, and NFL.com, and PFF. \
Whenever the user asks about a specific player’s outlook, injury status, pros/cons, or fantasy projections, you must call the web_search tool before answering. \
Do not guess.\
In additon to having web search enabled, you have access to the following tools: \
    - run_draft_simulation: This function triggers a draft simulation to run in the background.  This function should be called when the user requests you to simulate a draft. Note, the user request might not directly \
            use the words 'simulate' or 'draft' in their request. You, the agent, should be able to infer this when the user asks for predictions on who will be available in each round or something similar. \
            This function should NOT be called more than 1x unless the user explictly asks for a new simulation or adjusts the parameters of the simulation. If the user asks for more information on the results and/or players, the agent should use web search to get the information. If you are unsure about whether the user is asking for a new simulation or not, ask the user to confirm their request.\
            There is some nuance to calling this function in regards to the adp_csv_file. The adp_csv_file parameter is the absolute filepath of the file that contains the average draft position data for players. It is essential for the simulation. BUT, I want to let the user either provide the absolute path OR let you, the agent, retrieve the required data on the user's behalf. \
            If the user provides the filepath, use it directly as the adp_csv_file parameter. \
            If not, you will need to call the get_adp_data tool to retrieve the data. Let the user know that you will do this. Inform them that the data is being retrieved from FantasyPros but that retrieval can fail because scraping assumes static webpages.\
            The get_adp_data tool returns a dict with 2 keys: 'status' and 'file_path'. If the status key has a value of 'Success', then 'file_path' holds the absolute filepath of the ADP csv file and can be passed as the adp_csv_file parameter to the simulation. If the status key has a value of 'Failed', then the file_path key will be None and the simulation won't be able to run. Inform the user in that case. \
    - get_simulation_status_and_results: This function should be used to retrieve the status and/or results of the draft simulation. This function is \
    used to check the status of the simulation that is running in the background. Call this function when the user is asking for the status or results of the draft simulation. This function \
    should only be called if run_draft_simulation has been called earlier. \
    - create_file: This function creates a new local file. It should only be called if the user explicitly asks the agent to create a file, save data, results, or insights, or as part of saving data for the draft simulation as csv files. \
            It is passed 2 parameters: filename and new_content. Usually, the filename should be a filename provided by the user. Otherwise, if not provided, choose a filename that is relevant given the context of the conversation and the content being written. \
            Prior to populating new content, be sure to know exactly what the user wants to write and how it should be formatted. \
            Don't call this function haphazardly. Be intentional about calling this function.\
    - read_simulation_file: This function reads the simulate.py file which is the script that runs the draft simulation. This function should be called if the user asks for the intricacies of the simulation design. Use the contents of the file to give you context to answer the user's question.\
    - append_file: This function appends content to a file that was previously created by the LLM. This function should be called if appending to a file is needed. \
            The file_path parameter is the absolute path of the file to append to. The content_to_append parameter is the content to append to the file. \
            This function should only be called if create_file has been successfully called earlier. You will need the absolute file path of the file that was returned in the value of the status key by create_file to append to it. \
\
Some user requests may involve very large research tasks and extensive web searches. \
You are NOT responsible for automatically breaking down large tasks. \
Instead, your role is to help the user manage large tasks effectively:\
\
1. If the user gives you a large or ambiguous task, suggest how they might break it into smaller, manageable chunks. \
   - Example: “This task might be easier if we first do X, then Y, then Z. Would you like to start with X?” \
   - Do not attempt to execute an entire massive task in one step.\
\
2. You have the ability to:\
   - Write intermediate results or notes directly into the conversation. \
   - Use tools like `append_file` or `create_file` to persist partial results or progress if the user wants them saved externally.\
\
3. Important: Be aware of how this system works.\
   - If you do not call a tool during your turn, control of the conversation is automatically returned to the user. \
   - Returning control before a task is complete or progress is persisted will result in permanent loss of progress.\
\
4. Therefore:\
   - Always either (a) finish the requested task, or (b) persist intermediate progress before ending your turn. \
   - If the user has given you a task that is too large for one step, clearly tell them so and suggest a breakdown strategy. \
   - If you must return control before the task is finished, explicitly inform the user that the task is incomplete and how they can continue.\
NEVER claim to run tasks (other than the simulation) in the background. NEVER silently drop progress.\
Note, you do not have the ability to alter/modify the simulation code itself, so don't tell the user that you are able to alter the logic. You can only alter the parameters of the simulation."
# ------------------------------
# Job Management
# ------------------------------
jobs = {}


def spinner(stop_event, msg="Thinking..."):
    for c in itertools.cycle(['.', '..', '...']):
        if stop_event.is_set():
            sys.stdout.write('\r' + ' ' * (len(msg) + 3) + '\r')  # Clear the line before breaking
            sys.stdout.flush()
            break
        sys.stdout.write(f"\r{msg}{c} ")
        sys.stdout.flush()
        time.sleep(0.4)

def remove_bye(x):
  s = x['Player Team (Bye)']
  left_par = s.find('(')
  if left_par != -1:
    return s[:left_par-1].strip()
  else:
    return s.strip()

def get_team(x):
  s = x['Player Team']
  l = s.split(' ')
  if l[-1] in teams:
    return l[-1]
  else:
    return 'missing'

def get_player(x):
  s = x['Player Team']
  l = s.split(' ')
  if l[-1] in teams or l[-1] == 'DST':
    return ' '.join(l[:-1])
  else:
    return ' '.join(l)


def get_pos(row):
  pos_str = row['POS']
  pos = ''
  for c in pos_str:
    if c.isdigit():
      continue
    else:
      pos += c
  return pos


def get_adp_data():
  url = "https://www.fantasypros.com/nfl/adp/ppr-overall.php"
  headers = {"User-Agent": "Mozilla/5.0"}  # helps avoid bot blocks
  response = requests.get(url, headers=headers)
  file_name = "adp_data.csv"

  html = response.text

  soup = BeautifulSoup(html, "html.parser")

  table = soup.find("table", id="data")

  thead = table.find("thead")
  tbody = table.find("tbody")

  headers = []
  rows = []
  for tr in thead.find_all("tr"):
      for th in tr.find_all("th"):
          headers.append(th.text)

  for tr in tbody.find_all("tr"):
      row = []
      for td in tr.find_all("td"):
          row.append(td.text)
      rows.append(row)

  data = [headers] + rows

  df = pd.DataFrame(data[1:], columns=data[0])  # first row as headers

  df['ADP'] = df['AVG'].astype(float)
  df = df[['Player Team (Bye)', 'POS', 'ADP']]


  df['Player Team'] = df.apply(remove_bye, axis=1)
  df = df.drop(columns=['Player Team (Bye)'])
  df['Team'] = df.apply(get_team, axis=1)
  df['Player'] = df.apply(get_player, axis=1)
  df = df.drop(columns=['Player Team'])
  df['Position'] = df.apply(get_pos, axis=1)
  df = df[~df['Position'].isin(['CB', 'LB', 'DT'])].reset_index(drop=True)
  df = df.sort_values(by=['ADP'], ascending=True, ignore_index=True)
  df = df[['Player', 'Team', 'Position', 'ADP']]

  if df['Player'].isna().sum().item() or df['Position'].isna().sum().item():
    return {'status': 'Failed', 'filepath': None}
  
  if ((df['ADP'][1:]).reset_index(drop=True) < (df['ADP'][:-1]).reset_index(drop=True)).sum().item():
    return {'status': 'Failed', 'filepath': None}

  # Check if file already exists
  file_path = os.path.join(os.getcwd(), file_name)
  if os.path.exists(file_path):
    return {'status': 'Failed because adp_data.csv already exists in the current directory', 'filepath': None}
    
  # Write dataframe to CSV file in current directory
  df.to_csv(file_path, index=False)
  return {'status': 'Success', 'filepath': file_path}

def _run_script_thread(extra_args, job_id):
    try:
        result = subprocess.run(
            ["python3", "simulate.py"] + extra_args,
            capture_output=True,
            text=True
        )
        jobs[job_id]["result"] = {"stdout": result.stdout, "stderr": result.stderr}
    except Exception as e:
        jobs[job_id]["result"] = {"error": str(e)}
    finally:
        jobs[job_id]["done"] = True

def run_draft_simulation(num_teams, pick, draft_rounds, adp_csv_file, keepers_csv_file=None, num_sims=None):
    extra_args = [f"--num_teams={num_teams}", f"--pick={pick}", f"--draft_rounds={draft_rounds}", f"--adp_csv_file={adp_csv_file}"]
    if num_sims is not None:
        extra_args.append(f"--num_sims={num_sims}") #optional
    if keepers_csv_file is not None and len(keepers_csv_file) > 0:
        extra_args.append(f"--keepers_csv_file={keepers_csv_file}")

    job_id = str(uuid.uuid4())
    jobs[job_id] = {"done": False, "result": None}
    thread = Thread(target=_run_script_thread, args=(extra_args, job_id))
    thread.start()
    return {"job_id": job_id, "status": "started"}

def get_simulation_status_and_results(job_id):
    if job_id not in jobs:
        return {"error": "Invalid job ID"}
    job = jobs[job_id]
    if not job["done"]:
        return {"status": "running"}
    return {"status": "done", "result": job["result"]}

def create_file(filename, new_content):
    
    file_path = os.path.join(os.getcwd(), filename)
    
    # Prevent overwriting
    try:
        fd = os.open(file_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return {"status": f"Cannot overwrite existing file {file_path}"}

    # Check allowed extensions
    if not file_path.endswith(('.txt', '.md', '.csv')):
        os.close(fd)
        return {"status": "Only .txt, .md, and .csv files are allowed"}

    # Write content (with limit)
    if len(new_content) > 1_000_000:  # limit to 1MB
        os.close(fd)
        return {"status": "File content too large"}

    with os.fdopen(fd, "w") as f:
        f.write(new_content)

    llm_written_files.append(file_path)
    return {"status": f"File {filename} written successfully in the current directory with the absolute path: {file_path}."}

def append_file(file_path, content_to_append):
    """
    Append content to a file that was previously created by the LLM.
    Only allows appending to files that were created by create_file().
    
    Args:
        file_path: Absolute path of file to append to
        content_to_append: Content to append to the file
        
    Returns:
        dict: Contains status message
    """
    
    # Check if file was previously created by LLM
    if file_path not in llm_written_files:
        return {"status": f"Cannot append to {file_path} - file was not created by the agent"}
        
    # Check allowed extensions
    if not file_path.endswith(('.txt', '.md', '.csv')):
        return {"status": "Only .txt, .md, and .csv files are allowed"}
        
    # Check content size
    if len(content_to_append) > 1_000_000:  # limit to 1MB
        return {"status": "Content to append is too large"}
        
    try:
        with open(file_path, "a") as f:
            f.write(content_to_append)
            
        return {"status": f"Successfully appended content to {file_path}"}
        
    except Exception as e:
        return {"status": f"Error appending to file: {str(e)}"}


def read_simulation_file():
    """
    Read the simulate.py file from the current working directory.
            
    Returns:
        dict: Contains status and optionally file_content
    """
    filename = "simulate.py"
    file_path = os.path.join(os.getcwd(), filename)
        
    # Check file exists
    if not os.path.exists(file_path):
        return {"status": f"File {filename} not found"}
        
    # Read file (with size limit)
    try:
        # Read the file
        with open(file_path, 'r') as f:
            content = f.read()
            
        return {
            "status": "success",
            "file_content": content
        }
        
    except Exception as e:
        return {"status": f"Error reading file: {str(e)}"}


# ------------------------------
# Custom Tools Definition
# ------------------------------
custom_tools = [
    {
        "type": "function",
        "name": "run_draft_simulation",
        "description": "This function triggers a draft simulation to run in the background. \
            This function returns a dict with 2 keys: job_id and status. The status key will have a value of 'started' until the simulation is complete. The agent WILL NEED the job_id (string) later to get the results of the draft simulation. This function's parameters are inferred from the user's input. \
            The purpose of this function is to enable the user to get an idea of the best players available to draft in each round. It basically runs an automated mock draft. It is critical that the adp_csv_file contains data for AT LEAST 300 players for the upcoming {season} fantasy football season. \
            \
            The function should be called with the following parameters: \
            num_teams: Number of teams in the user's league (REQUIRED) \
            pick: The user's draft pick position (REQUIRED) \
            draft_rounds: Number of rounds in the draft (REQUIRED); must be between 14 and 16 (inclusive) \
            adp_csv_file: *Absolute* file path for player data in CSV format (REQUIRED); the csv schema must contain: 'Player (str), ADP (float), Position (str)' in some order where 'Position' is one of: QB, RB, WR, TE, K, DST and 'ADP' is the average draft position of the player; the data must be sorted by 'ADP' in ascending order. Should have at least 300 players. \
            keepers_csv_file: *Absolute* file path for keepers data in CSV format (OPTIONAL). If provided, the csv schema must be: 'Player (str), Position (str), Round (int), Team (int)' where 'Position' is one of: QB, RB, WR, TE, K, DST and 'Round' is the draft round being used to keep the player. 'Team' is the team that the player will be on where Team 1 is the first team to draft and Team 2 is the second team to draft in the first round and so on. 'Team' must be between 1 and num_teams (inclusive). \
            num_sims: Number of draft simulations to run (OPTIONAL) \
            \
            Ensure that the parameters of this function are extracted from the user's input. If the user is trying to run the simulation without providing the necessary parameters, let them know and ask them to provide the necessary parameters.",

        "parameters": {
            "type": "object",
            "properties": {
                "num_teams": {"type": "integer", "description": "Number of teams in the user's league (ie: 14)"},
                "pick": {"type": "integer", "description": "The user's draft pick position (ie: 1)"},
                "draft_rounds": {"type": "integer", "description": "Number of rounds in the draft (ie: 14)"},
                "adp_csv_file": {"type": "string", "description": "Absolute file path for player data in CSV format; the csv schema must contain: 'Player (str), ADP (float), Position (str)' in some order where 'Position' is one of: QB, RB, WR, TE, K, DST and 'ADP' is the average draft position of the player; the data must be sorted by 'ADP' in ascending order. Should have at least 300 players."},
                "keepers_csv_file": {"type": "string", "description": "Absolute file path for keepers data in CSV format; if provided, the csv schema must be: 'Player (str), Position (str), Round (int), Team (int)' where 'Position' is one of: QB, RB, WR, TE, K, DST and 'Round' is the draft round being used to keep the player. 'Team' is the team that the player will be on where Team 1 is the first team to draft and Team 2 is the second team to draft in the first round and so on. 'Team' must be between 1 and num_teams (inclusive)."},
                "num_sims": {"type": "integer", "description": "Number of draft simulations to run (ie: 2000)"},
            },
            "required": ["num_teams", "pick", "draft_rounds", "adp_csv_file"]
        }
    },
    {
        "type": "function",
        "name": "get_simulation_status_and_results",
        "description": "This function should be used to retrieve the status and/or results of the draft simulation. This function is \
            used to check the status of the simulation that is running in the background. \
            The parameter for this function is the job_id (string) returned by the run_draft_simulation function. \
            This function returns a dict. If the only key in the dict is 'error', it means that an incorrect job_id was passed in. \
            If the status key is present and has a value of 'running', it means that the simulation is still in progress so let the user know that the simulation is still running. \
            If the status key is present and has a value of 'done', it means that the simulation is complete and the results are available using the result key. \
            The result key will have a value of the results of the draft simulation stored as a dict, d. If the only key in dict, d, is error, it means that there was an exception when trying to run the simulation script.\
            Otherwise, the dict, d, will have a key for stdout which contains the simulation results which should be sent to the user. The simulation results will look like the following: \
                Most Likely Top 10 Players Available in Round 1: \
                Player 1_1, Team, Position, Percentage of simulations available, ADP \
                Player 2_1, Team, Position, Percentage of simulations available, ADP \
                ...\
                Player 10_1, Team, Position, Percentage of simulations available, ADP \
                Most Likely Top 10 Players Available in Round 2: \
                Player 1_2, Team, Position, Percentage of simulations available, ADP \
                Player 2_2, Team, Position, Percentage of simulations available, ADP \
                ...\
                Player 10_2, Team, Position, Percentage of simulations available, ADP \
                Most Likely Top 10 Players Available in Round X: \
                Keeper used in this round\
                ... \
                Most Likely Top 10 Players Available in Round 14: \
                Player 1_14, Team, Position, Percentage of simulations available, ADP \
                Player 2_14, Team, Position, Percentage of simulations available, ADP \
                ...\
                Player 10_14, Team, Position, Percentage of simulations available, ADP \
                \
                ADP: The ADP of the player is the average draft position of the player.\
                Team: The NFL team that the player is on. \
                Position: The position of the player. \
                Percentage of simulations available: The percentage of simulations that the player is available in the given round. \
                The agent should send the simulation results to the user in a friendly and easy to understand format. \
                The agent should not make up any information or make assumptions about the user's league or the draft.",
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "The job_id (string) returned by the run_draft_simulation function to be used to check the status and/or results of the draft simulation."}
            },
            "required": ["job_id"]
        }
    },
    {
        "type": "function",
        "name": "create_file",
        "description": "This function creates a new local file. The function should be called with the following parameters: \
            filename: The name of the file to be created (required) \
            new_content: The content to be written to the file (required) \
            This function returns a dict with a key for status. \
            If the value of the status key does not contain the word 'successfully', it means that the file was not created successfully. The message should be sent to the user. \
            If the value of the status key contains the word 'successfully', it means that the file was created successfully. The value of the status key should be sent to the user; the value includes the absolute path of the file that was created. Note, the absolute file path may be needed to append to the same file later.",
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {"type": "string"},
                "new_content": {"type": "string"}
            },
            "required": ["filename", "new_content"]
        }
    },
    {
        "type": "function",
        "name": "read_simulation_file",
        "description": "This function reads the simulate.py file from the current working directory. The purpose of this function is to give context to the user about the intricacies of the simulation design. No parameters are needed for this function.\
            The function returns a dict with a key for status and a key for file_content. The status key will have a value of 'success' if the file was read successfully. The file_content key will have the contents of the the file that was read. \
            If the value of the status key is not 'success', it means that the file was not read successfully. Typically, when the read fails, it's because the user is not executing agent.py from the root directory of the project. The value of the status key should be sent to the user.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "type": "function",
        "name": "append_file",
        "description": "This function appends content to a file that was previously created by the agent. The function should be called with the following parameters: \
            file_path: The absolute path of the file to append to (required) \
            content_to_append: The content to append to the file (required) \
            This function returns a dict with a key for status. \
            If the value of the status key does not contain the word 'successfully', it means that the file was not appended to successfully. The message should be sent to the user. \
            If the value of the status key contains the word 'successfully', it means that the file was appended to successfully. The value of the status key should be sent to the user; the value includes the absolute path of the file that was appended to.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "content_to_append": {"type": "string"}
            },
            "required": ["file_path", "content_to_append"]
        }
    },
    {
        "type": "function",
        "name": "get_adp_data",
        "description": "This function retrieves the ADP data for the upcoming {season} fantasy football season. The function should not be called with parameters. \
            This function returns a dict with a key named 'status' and a key named 'file_path'. The status key will have a value of 'Success' if the ADP data was retrieved successfully. If successful, then 'file_path' will hold the absolute file path of a csv file with the ADP data. The ADP data has the following schema: 'Player', 'Team', 'Position', 'ADP'. The ADP data will be sorted by 'ADP' in ascending order.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
]

# Include the built-in web search tool
tools = custom_tools + [{"type": "web_search"}]

# ------------------------------
# Agent Loop
# ------------------------------
def agent_chat(model):
    conversation = [{"role": "system", "content": SYSTEM_PROMPT}]

    print("""
    ╔═══════════════════════════════════════════════════════════════╗
    ║                                                               ║
    ║   ██████╗ ██████╗  █████╗ ███████╗████████╗                   ║
    ║   ██╔══██╗██╔══██╗██╔══██╗██╔════╝╚══██╔══╝                   ║
    ║   ██║  ██║██████╔╝███████║█████╗     ██║                      ║
    ║   ██║  ██║██╔══██╗██╔══██║██╔══╝     ██║                      ║
    ║   ██████╔╝██║  ██║██║  ██║██║        ██║                      ║
    ║   ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝        ╚═╝                      ║
    ║                                                               ║
    ║    █████╗  ██████╗ ███████╗███╗   ██╗████████╗                ║
    ║   ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝                ║
    ║   ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║                   ║
    ║   ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║                   ║
    ║   ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║                   ║
    ║   ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝                   ║
    ║                                                               ║
    ║   Your AI Fantasy Football Draft Assistant. I'm capable of:   ║
    ║   - Simulating/mocking drafts                                 ║
    ║   - Retrieving Average Draft Position (ADP) data for the      ║
    ║     upcoming fantasy football season                          ║
    ║   - Providing player insights and analysis                    ║
    ║   - Helping optimize your draft strategy                      ║
    ║   - Staying current with latest fantasy news                  ║
    ║   - Creating files to save data, results, and insights        ║
    ║   - Enter 'exit' or 'quit' to end the conversation.           ║
    ║                                                               ║
    ╚═══════════════════════════════════════════════════════════════╝
    """)
    
    while True:
        print('-----------------------------------------------------------------------')
        user_input = input("You: ")
        if user_input.lower() in {"exit", "quit"}:
            break

        conversation.append({"role": "user", "content": user_input})

        # Call the Responses API
        done = False
        while not done:
          
            stop_event = threading.Event()
            t = threading.Thread(target=spinner, args=(stop_event,))
            t.start()
  
            try:
                for attempt in range(max_retries):
                    try:
                        response = client.responses.create(
                            model=model,
                            input=conversation,
                            tools=tools
                        )
                        break  # success → exit loop
                    except RateLimitError as e:
                        wait = backoff * (2 ** (attempt+1))  # exponential backoff
                        print(f"OpenAI rate limit hit on your key (attempt {attempt+1}). Retrying in {wait:.1f}s...")
                        time.sleep(wait)
                        conversation.append({
                            "role": "system",
                            "content": "The API was rate limited. You may have to break the current task into smaller steps so fewer tokens are required per request."
                        })
                else:
                    raise RuntimeError("Max retries exceeded due to OpenAI rate limiting you. Please try again later. Session ending...")
            finally:
                stop_event.set()
                t.join()
            new_tool_call = False

            for o in response.output:
                conversation.append(o)
                if hasattr(o, "type") and o.type == "message":
                    # handle assistant text
                    content = "".join(c.text for c in o.content if hasattr(c, 'type') and c.type == 'output_text')
                    if content:
                        print("Agent:", content)
                        print('\n')

                elif hasattr(o, "type") and o.type == "function_call":
                    new_tool_call = True
                    tool_name = o.name
                    call_id = o.call_id
                    tool_args = json.loads(o.arguments)
                   

                    print(f"System: Agent wants to call: {tool_name} with args {tool_args}")

                    # run tool
                    if tool_name == "run_draft_simulation":
                        tool_result = run_draft_simulation(**tool_args)
                    elif tool_name == "get_simulation_status_and_results":
                        tool_result = get_simulation_status_and_results(**tool_args)
                    elif tool_name == "create_file":
                        tool_result = create_file(**tool_args)
                    elif tool_name == "read_simulation_file":
                        tool_result = read_simulation_file()
                    elif tool_name == "append_file":
                        tool_result = append_file(**tool_args)
                    elif tool_name == "get_adp_data":
                        tool_result = get_adp_data()

                    conversation.append({
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps(tool_result)
                    })

            # if no new tool calls remain, we're done
            if not new_tool_call:
                done = True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fantasy Football Draft Assistant - Agent Module",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    # Required arguments
    parser.add_argument(
        '--model',
        type=str,
        default="gpt-5-mini",
        choices=["gpt-5-mini", "gpt-5", "gpt-4.1-mini"],
        help='Model to use for the agent (optional; default is gpt-5-mini)'
    )
    args = parser.parse_args()

    agent_chat(model=args.model)

import os
import json
import uuid
import subprocess
from threading import Thread
from openai import OpenAI
from dotenv import load_dotenv
from datetime import date
load_dotenv()

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
season = date.today().year

# System prompt (configurable via env var AGENT_SYSTEM_PROMPT)
SYSTEM_PROMPT =  f"You are a fantasy football expert who grounds opinions based on facts and the latest news and projections, and you have taken on the role of a helpful, concise assistant. \
Your goal is to help the user in the upcoming {season} fantasy football season. \
You can run draft simulations given some inputs from the user. \
You can help the user prepare for the draft and by answering their questions about the draft and the upcoming NFL season in general by getting the latest news, information, and outlook from the web. \
You can save and write files to the local directory. \
Whenever you do use the web, use the best sources for {season} fantasy football data like ESPN, CBS, Yahoo, and NFL.com, and PFF. \
Whenever the user asks about a specific player’s outlook, injury status, pros/cons, or fantasy projections, you must call the web_search tool before answering. \
Do not guess.\
In additon to having web search enabled, you have access to the following tools: \
    - run_draft_simulation: This function triggers a draft simulation to run in the background.  This function should be called when the user requests you to simulate a draft. Note, the user request might not directly \
            use the words 'simulate' or 'draft' in their request. You, the agent, should be able to infer this when the user asks for predictions on who will be available in each round or something similar. \
            This function should NOT be called more than 1x unless the user explictly asks for a new simulation or adjusts the parameters of the simulation. If the user asks for more information on the results and/or players, the agent should use web search to get the information. If you are unsure about whether the user is asking for a new simulation or not, ask the user to confirm their request.\
            There is some nuance to calling this function in regards to the adp_csv_file. The adp_csv_file parameter is the absolute filepath of the file that contains the average draft position data for players. It is essential for the simulation. BUT, I want to let the user either provide the absolute path OR let you, the agent, create the file after web searching for the data. \
            If the user provides the filepath, use it directly as the adp_csv_file parameter. \
            If not, let the user know that you will do a web search youself. The web search needs to retrieve the player name, average draft position, and position for AT LEAST 200 players for the upcoming {season} fantasy football season. Get ADP data from ONE reputable source like ESPN, CBS, Yahoo, and NFL.com, or PFF. You should use the create_file tool to create a new csv file with the adp data. \
            Be mindful of the required schema of the adp_csv_file. The csv schema must be: 'Player (str), ADP (float), Position (str)'. 'Position' is one of: QB, RB, WR, TE, K, DST. \
            Choose a relevant filename for the adp_csv_file, write the content, and use the absolute filepath of the file containing the data you just wrote as the adp_csv_file parameter. This path can be found in the status key of the dict returned from the create_file tool. \
            \
    - get_simulation_status_and_results: This function should be used to retrieve the status and/or results of the draft simulation. This function is \
    used to check the status of the simulation that is running in the background. Call this function when the user is asking for the status or results of the draft simulation. This function \
    should only be called if run_draft_simulation has been called earlier. \
    - create_file: This function creates a new local file. It should only be called if the user explicitly asks the agent to create a file, save data, results, or insights, or as part of saving data for the draft simulation as csv files. \
            It is passed 2 parameters: filename and new_content. Usually, the filename should be a filename provided by the user. Otherwise, if not provided, choose a filename that is relevant given the context of the conversation and the content being written. \
            Prior to populating new content, be sure to know exactly what the user wants to write and how it should be formatted. \
            Don't call this function haphazardly. Be intentional about calling this function."

# ------------------------------
# Job Management
# ------------------------------
jobs = {}

def _run_script_thread(extra_args, job_id):
    try:
        result = subprocess.run(
            ["python3", "simulate_new.py"] + extra_args,
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

    return {"status": f"File {filename} written successfully in the current directory with the absolute path: {file_path}."}


# ------------------------------
# Custom Tools Definition
# ------------------------------
custom_tools = [
    {
        "type": "function",
        "name": "run_draft_simulation",
        "description": "This function triggers a draft simulation to run in the background. \
            This function returns a dict with 2 keys: job_id and status. The status key will have a value of 'started' until the simulation is complete. The agent WILL NEED the job_id (string) later to get the results of the draft simulation. This function's parameters are inferred from the user's input. \
            The purpose of this function is to enable the user to get an idea of the best players available to draft in each round. It basically runs an automated mock draft. \
            \
            The function should be called with the following parameters: \
            num_teams: Number of teams in the user's league (REQUIRED) \
            pick: The user's draft pick position (REQUIRED) \
            draft_rounds: Number of rounds in the draft (REQUIRED) \
            adp_csv_file: Absolute filename for player data in CSV format (REQUIRED); the csv schema must be: 'Player (str), ADP (float), Position (str)' where 'Position' is one of: QB, RB, WR, TE, K, DST and 'ADP' is the average draft position of the player; the data must be sorted by 'ADP' in ascending order. \
            keepers_csv_file: Absolute filename for keepers data in CSV format (OPTIONAL). If provided, the csv schema must be: 'Player (str), Position (str), Round (int), Team (int)' where 'Position' is one of: QB, RB, WR, TE, K, DST and 'Round' is the draft round being used to keep the player. 'Team' is the team that the player will be on where Team 1 is the first team to draft and Team 2 is the second team to draft in the first round and so on. 'Team' must be between 1 and num_teams (inclusive). \
            num_sims: Number of draft simulations to run (OPTIONAL) \
            \
            Ensure that the parameters of this function are extracted from the user's input. If the user is trying to run the simulation without providing the necessary parameters, let them know and ask them to provide the necessary parameters.",

        "parameters": {
            "type": "object",
            "properties": {
                "num_teams": {"type": "integer", "description": "Number of teams in the user's league (ie: 14)"},
                "pick": {"type": "integer", "description": "The user's draft pick position (ie: 1)"},
                "draft_rounds": {"type": "integer", "description": "Number of rounds in the draft (ie: 14)"},
                "adp_csv_file": {"type": "string", "description": "Absolute filename for player data in CSV format; the csv schema must be: 'Player (str), ADP (float), Position (str)' where 'Position' is one of: QB, RB, WR, TE, K, DST and 'ADP' is the average draft position of the player; the data must be sorted by 'ADP' in ascending order."},
                "keepers_csv_file": {"type": "string", "description": "Absolute filename for keepers data in CSV format; if provided, the csv schema must be: 'Player (str), Position (str), Round (int), Team (int)' where 'Position' is one of: QB, RB, WR, TE, K, DST and 'Round' is the draft round being used to keep the player. 'Team' is the team that the player will be on where Team 1 is the first team to draft and Team 2 is the second team to draft in the first round and so on. 'Team' must be between 1 and num_teams (inclusive)."},
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
                Player 1_1, Percentage of simulations available, ADP \
                Player 2_1, Percentage of simulations available, ADP \
                Player 3_1, Percentage of simulations available, ADP \
                Player 4_1, Percentage of simulations available, ADP \
                Player 5_1, Percentage of simulations available, ADP \
                Player 6_1, Percentage of simulations available, ADP \
                Player 7_1, Percentage of simulations available, ADP \
                Player 8_1, Percentage of simulations available, ADP \
                Player 9_1, Percentage of simulations available, ADP \
                Player 10_1, Percentage of simulations available, ADP \
                Most Likely Top 10 Players Available in Round 2: \
                Player 1_2, Percentage of simulations available, ADP \
                Player 2_2, Percentage of simulations available, ADP \
                Player 3_2, Percentage of simulations available, ADP \
                Player 4_2, Percentage of simulations available, ADP \
                Player 5_2, Percentage of simulations available, ADP \
                Player 6_2, Percentage of simulations available, ADP \
                Player 7_2, Percentage of simulations available, ADP \
                Player 8_2, Percentage of simulations available, ADP \
                Player 9_2, Percentage of simulations available, ADP \
                Player 10_2, Percentage of simulations available, ADP \
                Most Likely Top 10 Players Available in Round X: \
                Keeper used in this round\
                ... \
                Most Likely Top 10 Players Available in Round 14: \
                Player 1_14, Percentage of simulations available, ADP \
                Player 2_14, Percentage of simulations available, ADP \
                Player 3_14, Percentage of simulations available, ADP \
                Player 4_14, Percentage of simulations available, ADP \
                Player 5_14, Percentage of simulations available, ADP \
                Player 6_14, Percentage of simulations available, ADP \
                Player 7_14, Percentage of simulations available, ADP \
                Player 8_14, Percentage of simulations available, ADP \
                Player 9_14, Percentage of simulations available, ADP \
                Player 10_14, Percentage of simulations available, ADP \
                \
                ADP: The ADP of the player is the average draft position of the player.\
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
            If the value of the status key contains the word 'successfully', it means that the file was created successfully. The message should be sent to the user; the message should include the absolute path of the file that was created.",
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {"type": "string"},
                "new_content": {"type": "string"}
            },
            "required": ["filename", "new_content"]
        }
    }
]

# Include the built-in web search tool
tools = custom_tools + [{"type": "web_search"}]

# ------------------------------
# Agent Loop
# ------------------------------
def agent_chat():
    conversation = [{"role": "system", "content": SYSTEM_PROMPT}]

    print("""
    ╔═══════════════════════════════════════════════════════════════╗
    ║                                                               ║
    ║   ██████╗ ██████╗  █████╗ ███████╗████████╗                  ║
    ║   ██╔══██╗██╔══██╗██╔══██╗██╔════╝╚══██╔══╝                  ║
    ║   ██║  ██║██████╔╝███████║█████╗     ██║                     ║
    ║   ██║  ██║██╔══██╗██╔══██║██╔══╝     ██║                     ║
    ║   ██████╔╝██║  ██║██║  ██║██║        ██║                     ║
    ║   ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝        ╚═╝                     ║
    ║                                                               ║
    ║    █████╗  ██████╗ ███████╗███╗   ██╗████████╗              ║
    ║   ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝              ║
    ║   ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║                 ║
    ║   ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║                 ║
    ║   ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║                 ║
    ║   ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝                 ║
    ║                                                               ║
    ║   Your AI Fantasy Football Draft Assistant                    ║
    ║   - Simulates draft scenarios                                ║
    ║   - Provides player insights and analysis                    ║
    ║   - Helps optimize your draft strategy                       ║
    ║   - Stays current with latest fantasy news                   ║
    ║                                                              ║
    ╚═══════════════════════════════════════════════════════════════╝
    """)
    
    while True:
        user_input = input("You: ")
        if user_input.lower() in {"exit", "quit"}:
            break

        conversation.append({"role": "user", "content": user_input})

        # Call the Responses API
        done = False
        while not done:
            
            response = client.responses.create(
                model="gpt-5-mini",
                input=conversation,
                tools=tools
            )

            new_tool_call = False

            for o in response.output:
                conversation.append(o)
                if hasattr(o, "type") and o.type == "message":
                    # handle assistant text
                    content = "".join(c.text for c in o.content if hasattr(c, 'type') and c.type == 'output_text')
                    if content:
                        print("Agent:", content)

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

                    conversation.append({
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps(tool_result)
                    })

            # if no new tool calls remain, we're done
            if not new_tool_call:
                done = True

if __name__ == "__main__":
    agent_chat()

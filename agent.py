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
    - get_simulation_status_and_results: This function should be used to retrieve the status and/or results of the draft simulation. This function is \
    used to check the status of the simulation that is running in the background. Call this function when the user is asking for the status or results of the draft simulation. This function \
    should only be called if run_draft_simulation has been called earlier. \
    - create_file: This function creates a new local file. It should only be called if the user explicitly asks the agent to create a file or save data, results, or insights. \
        Don't call this function more than 2-3 times max."

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



def create_file(file_path, new_content):
    abs_path = os.path.realpath(file_path)  # resolves symlinks fully
    cwd = os.path.realpath(os.getcwd())

    # Ensure inside current directory
    if not abs_path.startswith(cwd + os.sep):
        return {"status": "Cannot create file outside current directory"}

    # Prevent overwriting
    try:
        fd = os.open(abs_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return {"status": f"Cannot overwrite existing file {file_path}"}

    # Check allowed extensions
    if not abs_path.endswith(('.txt', '.md')):
        os.close(fd)
        return {"status": "Only .txt and .md files are allowed"}

    # Write content (with limit)
    if len(new_content) > 1_000_000:  # limit to 1MB
        os.close(fd)
        return {"status": "File content too large"}

    with os.fdopen(fd, "w") as f:
        f.write(new_content)

    return {"status": f"File {file_path} written successfully."}


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
            keepers_csv_file: Absolute filename for keepers data in CSV format (OPTIONAL); if provided, the csv schema must be: 'Player (str), Position (str), Round (int), Team (int)' where 'Position' is one of: QB, RB, WR, TE, K, DST and 'Round' is the draft round being used to keep the player. 'Team' is the team that the player will be on where Team 1 is the first team to draft and Team 2 is the second team to draft in the first round and so on. 'Team' must be between 1 and num_teams (inclusive). \
            num_sims: Number of draft simulations to run (OPTIONAL) \
            \
            Ensure that the parameters of this function are extracted from the user's input. Do NOT make them up on your own. If the user is trying to run the simulation without providing the necessary parameters, let them know and ask them to provide the necessary parameters.",

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
            file_path: The absolute path to the file to be created (required) \
            new_content: The content to be written to the file (required) \
            Note, that the file_path should be an absolute filepath provided by the user in the user's input. Do NOT make up a file_path on your own. \
            Prior to populating new content, be sure to know exactly what the user wants to write and how it should be formatted. \
            Do NOT call this function more than a few times. This function returns a dict with a key for status. \
            If the value of the status key does not contain the word 'successfully', it means that the file was not created successfully. The message should be sent to the user. \
            If the value of the status key contains the word 'successfully', it means that the file was created successfully. The message should be sent to the user.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "new_content": {"type": "string"}
            },
            "required": ["file_path", "new_content"]
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
        response = client.responses.create(
            model="gpt-5-mini",
            input=conversation,
            tools=tools
        )
        
        conversation += response.output
        assistant_message = ""
        function_call = False
        for o in response.output:
            if hasattr(o, 'type') and o.type == 'message':
                content = o.content
                for c in content:
                    if hasattr(c, 'type') and c.type == 'output_text':
                        assistant_message += c.text
                        print("Agent:", assistant_message)
                        print("\n")

            elif hasattr(o, 'type') and o.type == 'function_call':
                function_call = True
                tool_name = o.name
                tool_args = json.loads(o.arguments)
                call_id = o.call_id

                print(f"System: Agent wants to call: {tool_name} with args {tool_args}")


                if tool_name == "run_draft_simulation":
                    tool_result = run_draft_simulation(**tool_args)
                elif tool_name == "get_simulation_status_and_results":
                    tool_result = get_simulation_status_and_results(**tool_args)
                elif tool_name == "create_file":
                    tool_result = create_file(**tool_args)
                else:
                    raise ValueError(f"Invalid tool name: {tool_name}")

                # Append tool output to conversation
                conversation.append({
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(tool_result)
                })
        
        # Ask model to reason about the tool output
        if function_call:
            followup = client.responses.create(
                model="gpt-5-mini",
                input=conversation,
                tools=tools,
                instructions=f"Reason about the tool output and the context of the conversation and respond appropriately to the user"
            )

            followup_message = ""
            for o in followup.output:
                if hasattr(o, 'type') and o.type == 'message':
                    content = o.content
                    for c in content:
                        if hasattr(c, 'type') and c.type == 'output_text':
                            followup_message += c.text

            print("Agent:", followup_message)
            print("\n")
            conversation += followup.output
        

if __name__ == "__main__":
    agent_chat()

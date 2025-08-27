# Fantasy Football Draft Assistant

A grounded, intelligent LLM-powered agent that assists in simulating, researching, and preparing for fantasy football drafts using Monte Carlo simulations and real-time data analysis. The agent runs fully from your command line! A brief description of features and how-to-run instructions are below. For more in-depth discussion and a demo, see my Medium post: **https://medium.com/p/691d6fcda46f/edit**

## 🏈 Features

### 🤖 AI Agent Capabilities

In addition to the capabilties of modern LLMs, this LLM-powered agent can:
- **Realistically simulate thousands of drafts to predict likely players available at the user's pick in each round**
- **Analyze simulation results and provide strategic insights and strategies** 
- **Use the simulation results to research specific players and retrieve the most up-to-date news and insights from reputable soruces like ESPN, PPF, Yahoo, CBS Sports, etc**
- **Generate draft preparation reports and save results, reports, and insights to files locally**


### Core Functionality
- **Monte Carlo Draft Simulations**: Run thousands of draft simulations to predict player availability
- **LLM-Powered Analysis**: AI agent provides insights, research, and draft strategy recommendations
- **Real-time Data Integration**: Web scraping/search for latest ADP data, injury updates, and player news
- **Keeper League Support**: Handle keepers and their draft round assignments
- **ADP Data Support**: Optionally enables the user to provide ADP data that becomes the backbone of the simulation if user is particularly opinionated

## 📋 Requirements

- Developed and tested with Python 3.11.2
- OpenAI API key
- Internet connection for web scraping

## 🚀 Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/ijamil1/FFDraftAgent.git
   cd FFDraftAgent
   ```
2. **Create and activate virtual environment** (recommended):
   ```bash
   # On Windows
   python3 -m venv venv
   .\venv\Scripts\activate

   # On macOS/Linux
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
4. **Copy and configure environment file**:
   ```bash
   cp .env.example .env
   ```
   Then edit `.env` to add your OpenAI API key.

    ```env
   OPENAI_API_KEY=your_openai_api_key_here
   ```

## 🎯 Usage -- Running the Agent
```bash
python3 agent.py
```

## 📊 Data Format

### ADP Data (Optional -- agent can retrieve data on user's behalf)
CSV file with columns: `Player`, `Position`, `ADP` (Team is optional -- refers to player's NFL team)
```csv
Player,Team,Position,ADP
Ja'Marr Chase,CIN,WR,1.0
Bijan Robinson,ATL,RB,2.2
...
```

### Keepers Data (Optional)
CSV file with columns: `Player`, `Position`, `Round`, `Team` where Team refers to the **fantasy** team that the player will be kept on. Team 1 is the team drafting first in the 1st round; Team 2 is the team drafting second in the 1st round and so on.
```csv
Player,Position,Round,Team
Nico Collins,WR,13,1
Jayden Daniels,QB,6,2
...
```

For both of the data elements above, `Position` must be one of: QB, RB, WR, TE, K, DST.

## 🎮 Example Workflow

1. **Prepare ADP data**: Retrieve ADP data and ensure the CSV is formatted correctly. NOTE: agent can pull ADP data on your behalf so this step is **optional**
2. **Set up keepers**: Create keepers CSV and ensure it is formatted correctly. NOTE: **optional** step; can be run without keepers
3. **Run agent**: Execute python3 agent.py
4. **Ask questions and interact with the agent. As a start, it might be helpful to ask it what it does!**
---

**Happy Drafting! 🏈**
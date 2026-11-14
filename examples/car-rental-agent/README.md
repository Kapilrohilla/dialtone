# Example: Northwind Car Rentals driver lead qualifier

A complete, ready-to-load agent for **Northwind Car Rentals**, a fictional fleet company that rents cars to
ride-hailing drivers. "Maya", its AI calling assistant, phones driver-partner leads in Hindi and Hinglish,
checks their city and licence, explains the right plan, answers questions from approved figures only, and
records the outcome (interested, not eligible, callback…) for the telecalling team.

Every name, figure and rule here is made up. Use it as a template for your own agent.

## What's in this folder

| File | What it is |
| --- | --- |
| `agent.json` | The agent: name, persona, language, settings (including the company identity), custom expressions, the knowledge it uses and its workflow graph. Same fields as the console's agent editor. |
| `script.md` | The agent's script. Each `## Title` becomes one script section. `{{lead.x}}` is filled from the lead record. |
| `knowledge.md` | Approved information: cities, eligibility, prices, plan routing and offers. The agent quotes nothing that isn't here. |
| `.env.example` | The `AGENT_*` identity variables for the worker, set to Northwind's values. |
| `load.py` | Loads all of the above into a workspace as a draft agent. Safe to run again. |

## Identity: company, persona, pronunciation, consent line

The agent's core prompt names no company. Who it speaks for comes from configuration, with the published
agent winning over the worker's environment, and the environment over a generic default:

| Setting | Per agent (`agent.json`) | Worker env | Default when unset |
| --- | --- | --- | --- |
| Company name | `settings.company_name` | `AGENT_COMPANY_NAME` | no company is named |
| Persona name | `persona_name` | `AGENT_PERSONA_NAME` | the agent gives no name |
| Pronunciation of the company name | `settings.name_pronunciation` | `AGENT_NAME_PRONUNCIATION` | no pronunciation rule |
| Recording consent line | `settings.consent_line` | `AGENT_CONSENT_LINE` | "This call is being recorded for quality purposes." (an empty `AGENT_CONSENT_LINE` turns it off) |

The env values are what the built-in agent uses when no console agent is published for a number.

Note: the console's agent editor doesn't show the three `settings.*` identity fields yet, and saving the
agent's settings from the console keeps only the settings it knows. If that happens, run `load.py` again
or rely on the worker env values.

## Load it

1. Add the identity variables to the agent worker's `.env`:

   ```bash
   cat examples/car-rental-agent/.env.example >> agent/.env
   ```

2. Load the agent, its knowledge document and its workflow into a workspace (from `server/`, with the
   server's database configured):

   ```bash
   cd server
   WORKSPACE=northwind python manage.py shell < ../examples/car-rental-agent/load.py
   ```

   `WORKSPACE` is the slug of the workspace to load into; it is created if it doesn't exist. To use a new
   workspace, add yourself to it: `python manage.py create_member you@example.com --workspace northwind`.

3. Open the console, find **Northwind driver lead qualifier**, run it with **Test chat**, give it
   a phone number and publish it.

To load it by hand instead, create the knowledge document from `knowledge.md`, a workflow with the graph in
`agent.json`, and an agent with the remaining fields, pasting each `## Title` section of `script.md` into
the script.

## Try a call with a lead record

Dispatch the agent with JSON metadata so it skips what it already knows:

```json
{"lead_id": "NW-1001", "name": "Ramesh", "city": "Pune", "previously_interested": true}
```

# SKILLS.md

---
name: agent-creator  
description: Creates an agent based on the provided input by the user
---

Triggered when: Use this skill when the user is asking to create an agent or change workflow that will be solved by creation of an agent

# Instructions
- Role: Clearly define what role the agent plays in the entire flow
- Capabilities: Define the capabilities of the agents - what all it should accomplish and what tools are available
- Pattern: Choose appropriate one - ReAct (Reason + Act), Plan and Execute, etc.
- Tools list: Define all tools available to the agents
  1. The tools should have a clear goal
  2. The tools description must be extremely clear and descriptive
  3. Well-defines input and output format for the tool
  4. Error recovery: Analyze the error and understand how to recover from the tool failure
- Budgeting: Budget estimate the agent should use to complete its task, max budget so that it does not get stuck in a loop
- Failure Handling: How will the agent recover from failure in case of LLM/Tool/Other failure. Example: Retry with backoff
- I/O Format: What the agent expects as input and what format output will be given
- Avoiding loops: How will the agent avoid loops (max_iterations, same tool calls with same arguments)


---
name: mcp-enabler  
description: Helps to properly break down MCP requirements and create/update MCP client/servers/host with well defined outcomes
---

Triggered when: Use this skill when creating anything MCP server/host/client related

# Instructions
- Role: Create well defined MCP clients and server with proper roles and responsibilites
- Layers:
   1. Data Layer:
     - Clearly define the data layer components
     - Server Features: Decide the features available on the MCP server
     - Client Features: What can the server ask as input
     - Utility Features: Feedback using notifications to user, progress tracking
   2. Transport Layer:
     - Stdio transport: Use for local I/O
     - Streamable HTTP transport: For all other communication
- Primitives:
 1. Tools: To be used for Executable functions that AI applications can invoke to perform actions (e.g., file operations, API calls, database queries)
 2. Resources: Have data sources that provide properly parsed responses
 3. Prompts: Create reusable templates that help structure interactions with LLMs

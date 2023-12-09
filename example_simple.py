import asyncio
from chat_agent.chat_agent import ChatAgent
from chat_agent.tools import tool_list_files, tool_read_file, tool_replace_file, tool_text_to_speech, tool_create_image
from chat_agent.tools import tool_add_task, tool_remove_task, tool_list_tasks

# give your agent some tools to work with
agent = ChatAgent(
    tools=[tool_list_files, tool_read_file, tool_replace_file, tool_text_to_speech, tool_create_image], debug=False)


# run the agent in a loop
async def run_loop():
    while True:
        question = input("> ")
        print("thinking...")
        message = await agent.send_message(question)
        if message:
            print(message)

if __name__ == "__main__":
    asyncio.run(run_loop())

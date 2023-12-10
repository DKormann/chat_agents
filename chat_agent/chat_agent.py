from openai import OpenAI
import os
from dotenv import load_dotenv
from typing import Literal
import tiktoken
import json
import re
from colored import Fore, Style

from chat_agent.chat_agent_config import ChatAgentConfig, default_commands
from chat_agent.tools import ToolChain
from chat_agent.tools import tool_functions

load_dotenv()

client = OpenAI(
    api_key=os.getenv('OPENAI_API_KEY')
)

Role = Literal["user", "assistant", "system"]

enc = tiktoken.encoding_for_model("gpt-4")


class ChatAgent:
    def __init__(self,
                 config: ChatAgentConfig = ChatAgentConfig(),
                 debug: bool = None,):
        self.history = []
        self.config = config
        if debug:
            self.config.debug = debug

        if self.config.system_prompt:
            self.history.append(
                {"role": "system", "content": self.config.system_prompt})

        self.tools = ToolChain(
            self.config.tools, debug=self.config.debug, agent=self)

        self.all_time_tokens_input = 0
        self.all_time_tokens_output = 0

        self.memory_files = self.config.start_memory_files

        # this can be used by tools to store data
        self.data = {}

        if self.config.save_file:
            if os.path.isfile(self.config.save_file) and self.config.load_from_file:
                self.load_from_file(self.config.save_file)
            else:
                self.save_to_file(self.config.save_file)

    def reset(self):
        self.clear_history(save=False)

        if self.config.reset_token_count:
            self.all_time_tokens_input = 0
            self.all_time_tokens_output = 0

        self.data = {}

        # clear memory will also save the agent
        self.clear_memory()

    def clear_history(self, save: bool = True):
        self.history = []
        if self.config.system_prompt:
            self.history.append(
                {"role": "system", "content": self.config.system_prompt})
        if save:
            self.try_save()

    def try_save(self):
        if self.config.save_file and self.config.save_to_file:
            if os.path.dirname(self.config.save_file):
                os.makedirs(os.path.dirname(
                    self.config.save_file), exist_ok=True)

            self.save_to_file(self.config.save_file)

    def save_to_file(self, path: str):
        self.log(f"saving to file {path}")
        config_dict = self.config.__dict__
        # remove tools from config
        data = {
            "data": self.data,
            "config": config_dict,
            "memory_files": self.memory_files,
            "history": self.history,
            "all_time_tokens_input": self.all_time_tokens_input,
            "all_time_tokens_output": self.all_time_tokens_output
        }

        json_string = json.dumps(data, default=lambda x: x.__dict__)
        with open(path, "w") as f:
            f.write(json_string)

    def load_from_file(self, path: str):
        custom_commands = self.config.commands
        custom_tools = self.config.tools

        self.log(f"loading from file {path}")
        with open(path, "r") as f:
            data = json.loads(f.read())

        self.data = data["data"]
        self.config = ChatAgentConfig(**data["config"])

        # go through all tools and custom tools and find the right functions
        for tool in self.config.tools:
            if not self.assign_tool_function(tool, custom_tools):
                # remove tool
                name = tool["info"]["function"]["name"]
                self.log(f"Could not add tool {name}, removing...", "warning")
                self.config.tools.remove(tool)

        # go through all commands and find the right functions
        for command in self.config.commands:
            if not self.assign_command_function(command, custom_commands):
                # remove command
                name = command["name"]
                self.log(
                    f"Could not add command {name}, removing...", "warning")
                self.config.commands.remove(command)

        self.tools = ToolChain(
            self.config.tools, debug=self.config.debug, agent=self)
        self.memory_files = data["memory_files"]
        self.history = data["history"]
        self.all_time_tokens_input = data["all_time_tokens_input"]
        self.all_time_tokens_output = data["all_time_tokens_output"]

    def assign_tool_function(self, tool, custom_tools):
        name = tool["info"]["function"]["name"]
        if name in tool_functions:
            tool["function"] = tool_functions[name]
            return True
        else:
            for custom_tool in custom_tools:
                if name == custom_tool["info"]["function"]["name"]:
                    tool["function"] = custom_tool["function"]
                    return True
        return False

    def assign_command_function(self, command, custom_commands):
        for default_command in default_commands + custom_commands:
            if command["name"] == default_command["name"]:
                command["function"] = default_command["function"]
                return True
        return False

    def info(self):
        info = f"ChatAgent named {self.config.name}:\n\ndescription: {self.config.description or 'No description'}\nmodel: {self.config.model}\n\n"

        if self.config.debug:
            info += "debug mode: on\n\n"
        else:
            info += "debug mode: off\n\n"

        if self.config.system_prompt:
            info += f"system prompt: {self.config.system_prompt}\n\n"

        if self.memory_files:
            info += "memory files: \n"
            for memory_file in self.memory_files:
                info += f"- {memory_file}\n"
            info += "\n"

        if self.config.always_in_memory_files:
            info += "always in memory files: \n"
            for memory_file in self.config.always_in_memory_files:
                info += f"- {memory_file}\n"
            info += "\n"

        if self.tools:
            info += "available tools: \n"
            for tool_dict in self.tools.tool_info:
                info += f"- {tool_dict['function']['name']}\n"
            info += "\n"

        info += self.all_commands() + "\n"

        info += f"Input token count: {self.all_time_tokens_input}\n"
        info += f"Output token count: {self.all_time_tokens_output}\n"

        return info

    def all_commands(self):
        if not self.config.commands:
            return ""

        commands = "available commands:\n"
        for command in self.config.commands:
            commands += f"- {command['name']} {command['description']}\n"

        return commands

    def add_message_to_history(self, role: Role, content: str):
        self.log(f"{role}: {content}")

        self.history.append({"role": role, "content": content})

        # write to file
        if self.config.chat_file:
            if os.path.dirname(self.config.chat_file):
                os.makedirs(os.path.dirname(
                    self.config.chat_file), exist_ok=True)

            with open(self.config.chat_file, "w") as f:
                f.write(str(self))

        self.try_save()

    def __str__(self):
        string = "\n"
        for message in self.history:
            string += f"\n\n> {message['role']}:\n{message['content']}"
        if len(self.history) == 0:
            string += "No messages yet"
        string += "\n\n"
        return string

    def log(self, message: str, level: str = "info"):
        if self.config.name:
            message = f"{self.config.name}: {message}"
        if self.config.debug or level == "warning" or level == "error":
            if level == "warning":
                print(Fore.YELLOW + message + Style.RESET)
            elif level == "error":
                print(Fore.RED + message + Style.RESET)
            else:
                print(message)
        if self.config.log_file:
            if os.path.dirname(self.config.log_file):
                os.makedirs(os.path.dirname(
                    self.config.log_file), exist_ok=True)

            with open(self.config.log_file, "a") as f:
                f.write(message + "\n")

    def add_memory_file(self, path: str):
        self.memory_files.append(path)

        if len(self.memory_files) > self.config.max_memory_files:
            self.memory_files.pop(0)

        self.try_save()

    def has_memory(self, path: str):
        if path in self.config.always_in_memory_files:
            return True

        if path in self.memory_files:
            return True

        return False

    def clear_memory(self, save: bool = True):
        self.memory_files = self.config.start_memory_files

        if save:
            self.try_save()

    def remove_memory(self, path: str):
        if path in self.memory_files:
            self.memory_files.remove(path)
            self.try_save()
        else:
            raise FileNotFoundError(f"file {path} not in memory")

    def set_debug(self, debug: bool):
        self.config.debug = debug
        self.tools.debug = debug

    def add_memories_to_messages(self, messages: list):
        for memory_file in self.memory_files:
            try:
                with open(memory_file, "r") as f:
                    content = f.read()

                if self.config.show_line_numbers:
                    content = "\n".join(
                        [f"{i + 1}: {line}" for i, line in enumerate(content.split("\n"))])

                messages.append(
                    {"role": "system", "content": f"START FILE CONTENT OF {memory_file}\n{content}\nEND FILE CONTENT OF {memory_file}"})
            except Exception:
                self.log(f"could not read memory file {memory_file}")

        for memory_file in self.config.always_in_memory_files:
            try:
                with open(memory_file, "r") as f:
                    content = f.read()

                if self.config.show_line_numbers:
                    content = "\n".join(
                        [f"{i + 1}: {line}" for i, line in enumerate(content.split("\n"))])

                messages.append(
                    {"role": "system", "content": f"START FILE CONTENT OF {memory_file}\n{content}\nEND FILE CONTENT OF {memory_file}"})
            except Exception:
                self.log(f"could not read memory file {memory_file}")

    async def react(self):
        messages = self.history[-self.config.history_max_messages:]

        self.add_memories_to_messages(messages)
        self.log('Last message:')
        self.log(messages[-1])

        token_count = 0
        for message in messages:
            token_count += len(enc.encode(message['content']))

        self.all_time_tokens_input += token_count

        self.log(
            f"input token count: {token_count} ({self.all_time_tokens_input}) - current (total)")
        self.log('Sending request...')

        response_format = {
            "type": "json_object"} if self.config.answer_json else None
        completion = client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            response_format=response_format,
            tools=self.tools.tool_info if self.tools else None,
        )
        self.log('Received response!')

        if completion.choices[0].message.content:
            output_tokens = len(enc.encode(
                completion.choices[0].message.content))

            self.all_time_tokens_output += output_tokens
            self.log(
                f"output token count: {output_tokens} ({self.all_time_tokens_output}) - current (total)")

            self.add_message_to_history("assistant",
                                        completion.choices[0].message.content)

            if self.config.answer_json:
                return json.loads(completion.choices[0].message.content)

            return completion.choices[0].message.content

        if completion.choices[0].message.tool_calls and self.tools:
            for tool_call in completion.choices[0].message.tool_calls:
                self.all_time_tokens_output += len(
                    enc.encode(tool_call.function.name)) + len(
                    enc.encode(tool_call.function.arguments))

                function_message = await self.tools.tool_call(tool_call)
                self.add_message_to_history("system", function_message)

            if self.config.loop_function_call:
                return await self.react()

    def check_for_commands(self, message: str):
        if not self.config.commands:
            return False

        for command in self.config.commands:
            regex = command["regex"] if "regex" in command else None
            if (regex and re.match(regex, message)) or (not regex and message == command["name"]):
                self.log(f"command {command['name']} triggered")
                return command["function"](self, message)

        return False

    async def send_message(self, message: str, role: Role = "user"):
        if self.config.check_for_commands and role == "user":
            command = self.check_for_commands(message)
            if command:
                return command

        self.add_message_to_history(role, message)

        return await self.react()

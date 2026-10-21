"""
The project's chat with the Chat Agent (flows/change_router.py).

Send calls run_chat, then redraws the chat from chat_messages, so the chat panel always
shows what the Chat Agent has in its history, including a Change Router's clarifying
question. Send is disabled while a message is answered; app.py refreshes the jobs panel
after each message.
"""

import gradio as gr

from alikable.flows import change_router
from alikable.projects import Project

PLACEHOLDER = ("Ask about the project, ask for a change (\"make the header dark\"), ask for a check "
               "(\"is every page accessible?\"), or approve a build that is waiting.")


# The chatbot draws its placeholder edge to edge; give it room to breathe (app.py passes CSS to launch)
CSS = ".alikable-chat .placeholder { padding: 1.5rem 2.5rem; text-align: center; }"


class ChatScreen:
    def __init__(self, chat_id: gr.BrowserState):
        self.chat_id = chat_id
        self.title = gr.Markdown()
        self.chatbot = gr.Chatbot(label="Chat", height=480, feedback_options=None, placeholder=PLACEHOLDER,
                                  elem_classes="alikable-chat")
        with gr.Row():
            self.message = gr.Textbox(show_label=False, placeholder="Message Alikable", scale=5, autofocus=True)
            self.send = gr.Button("Send", variant="primary", scale=1)
        # finishes when a message has been answered; app.py refreshes the jobs panel after it
        self.sent = gr.on([self.send.click, self.message.submit], self._send,
                          [self.chat_id, self.message, self.chatbot], self.outputs)

    @property
    def outputs(self) -> list:
        return [self.title, self.chatbot, self.message, self.send]

    def render(self, project: Project) -> dict:
        return {self.title: f"## {project.title}",
                self.chatbot: change_router.chat_messages(project.chat_id),
                self.message: "", self.send: gr.Button(interactive=True)}

    def _send(self, chat_id: str, message: str, shown: list):
        if not message.strip():
            yield {self.message: ""}
            return
        yield {self.message: "", self.send: gr.Button(interactive=False),
               self.chatbot: [*shown, {"role": "user", "content": message}]}
        try:
            change_router.run_chat(message, chat_id)
        except Exception as e:
            gr.Warning(f"The Chat Agent failed ({e}). Send the message again.")
            yield {self.message: message, self.send: gr.Button(interactive=True),
                   self.chatbot: change_router.chat_messages(chat_id)}
            return
        yield {self.chatbot: change_router.chat_messages(chat_id), self.send: gr.Button(interactive=True)}

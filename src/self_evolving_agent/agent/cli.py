from self_evolving_agent.agent.llm import FakeLLM, LLMClient


def run_agent(llm: LLMClient) -> None:
    messages = [
        {
            "role": "user",
            "content": "Hello",
        }
    ]

    response = llm.complete(messages)
    print(response)


def main() -> None:
    llm = FakeLLM()
    run_agent(llm)
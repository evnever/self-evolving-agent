from self_evolving_agent.agent.llm import FakeLLM


def test_fake_llm_complete():
    llm = FakeLLM()
    
    response = llm.complete(
        [
            {
                "role": "user",
                "content": "Hello",
            }
        ]
    )

    assert response == "fake response"
    


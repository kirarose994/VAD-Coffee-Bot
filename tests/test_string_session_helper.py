import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from generate_telegram_string_session import (API_HASH_PROMPT, API_ID_PROMPT,
    CODE_PROMPT, PASSWORD_PROMPT, PHONE_PROMPT, SessionSetupError,
    generate_string_session)


class FakeSession:
    def save(self):return "generated-session-secret"


class FakeClient:
    def __init__(self):self.session=FakeSession();self.disconnected=False;self.values=[]
    async def start(self,phone,code_callback,password):
        self.values=[phone(),code_callback(),password()]
    async def disconnect(self):self.disconnected=True


class StringSessionHelperTests(unittest.IsolatedAsyncioTestCase):
    async def test_prompts_and_returns_memory_only_string_session(self):
        client=FakeClient();prompts=[]
        answers={PHONE_PROMPT:"+15551234567",CODE_PROMPT:"12345",
            PASSWORD_PROMPT:"two-factor-secret"}
        def read(prompt):prompts.append(prompt);return answers[prompt]
        result=await generate_string_session(
            environ={"TELEGRAM_API_ID":"12345","TELEGRAM_API_HASH":"api-hash-secret"},
            input_fn=read,secret_input_fn=read,client_factory=lambda api_id,api_hash:client)
        self.assertEqual(result,"generated-session-secret")
        self.assertEqual(prompts,[PHONE_PROMPT,CODE_PROMPT,PASSWORD_PROMPT])
        self.assertTrue(client.disconnected)

    async def test_missing_api_credentials_use_exact_interactive_prompts(self):
        client=FakeClient();prompts=[]
        answers={API_ID_PROMPT:"12345",API_HASH_PROMPT:"api-hash-secret",
            PHONE_PROMPT:"+15551234567",CODE_PROMPT:"12345",PASSWORD_PROMPT:"password"}
        def read(prompt):prompts.append(prompt);return answers[prompt]
        await generate_string_session(environ={},input_fn=read,secret_input_fn=read,
            client_factory=lambda api_id,api_hash:client)
        self.assertEqual(prompts,[API_ID_PROMPT,API_HASH_PROMPT,PHONE_PROMPT,
            CODE_PROMPT,PASSWORD_PROMPT])

    async def test_invalid_api_id_refuses_before_client_creation(self):
        with self.assertRaises(SessionSetupError):
            await generate_string_session(environ={"TELEGRAM_API_ID":"invalid",
                "TELEGRAM_API_HASH":"secret"},client_factory=lambda api_id,api_hash:FakeClient())


if __name__ == "__main__":unittest.main()

import argparse
import asyncio
import os
import sys

import aiohttp
from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import EndFrame, LLMMessagesFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.cartesia import CartesiaTTSService
from pipecat.services.openai import OpenAILLMService
from pipecat.transports.services.daily import DailyParams, DailyTransport
from pipecat.transports.services.helpers.daily_rest import DailyRESTHelper

logger.remove(0)
logger.add(sys.stderr, level="DEBUG")

daily_api_key = os.getenv("DAILY_API_KEY", "")
daily_api_url = os.getenv("DAILY_API_URL", "https://api.daily.co/v1")


async def main(room_url: str, token: str, callId: str):
    transport = DailyTransport(
        room_url,
        token,
        "Chatbot",
        DailyParams(
            api_url=daily_api_url,
            api_key=daily_api_key,
            audio_in_enabled=True,
            audio_out_enabled=True,
            camera_out_enabled=False,
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
            transcription_enabled=True,
        ),
    )

    tts = CartesiaTTSService(
        api_key=os.getenv("CARTESIA_API_KEY"),
        voice_id="79a125e8-cd45-4c13-8a67-188112f4dd22",  # British Lady
    )

    llm = OpenAILLMService(api_key=os.getenv("OPENAI_API_KEY"), model="gpt-4o")

    messages = [
        {
            "role": "system",
            "content": "You are Chatbot, a friendly, helpful robot. Your goal is to demonstrate your capabilities in a succinct way. Your output will be converted to audio so don't include special characters in your answers. Respond to what the user said in a creative and helpful way, but keep your responses brief. Start by saying 'Oh, hello! Who dares dial me at this hour?!'.",
        },
    ]

    context = OpenAILLMContext(messages)
    context_aggregator = llm.create_context_aggregator(context)

    pipeline = Pipeline(
        [
            transport.input(),
            context_aggregator.user(),
            llm,
            tts,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(pipeline, PipelineParams(allow_interruptions=True))

    def get_phone_number(callId: int) -> str:
        if callId % 2 == 0:
            return "+14155204406"
        else:
            return "+19499870006"

    @transport.event_handler("on_call_state_updated")
    async def on_call_state_updated(transport, state):
        logger.info(f"on_call_state_updated, state: {state}")
        dialout_id = None

        if state == "joined":
            logger.info(f"on_call_state_updated {state}")

            backoff_time = 1  # Initial backoff time in seconds

            for _ in range(3):
                try:
                    phone_number = get_phone_number(int(callId))
                    logger.debug(f"Starting dialout to {phone_number}")
                    settings = {
                        "phoneNumber": phone_number,
                        "display_name": "Dialout User",
                    }
                    dialout_id = await transport.start_dialout(settings)
                    break  # Break out of the loop if start_dialout is successful
                except Exception as e:
                    logger.error(f"Error starting dialout: {e}")
                    await asyncio.sleep(backoff_time)  # Wait for the current backoff time
                    backoff_time *= 2  # Double the backoff time for the next attempt

        if state == "left":
            logger.info(f"on_call_state_updated {state}")
            # await transport.stop_dialout(dialout_id)
            async with aiohttp.ClientSession() as aiohttp_session:
                print(f"Deleting room: {room_url}")
                rest = DailyRESTHelper(
                    daily_api_key=os.getenv("DAILY_API_KEY", ""),
                    daily_api_url=os.getenv("DAILY_API_URL", "https://api.daily.co/v1"),
                    aiohttp_session=aiohttp_session,
                )
                await rest.delete_room_by_url(room_url)

    @transport.event_handler("on_first_participant_joined")
    async def on_first_participant_joined(transport, participant):
        await transport.capture_participant_transcription(participant["id"])
        await task.queue_frames([LLMMessagesFrame(messages)])

    @transport.event_handler("on_participant_left")
    async def on_participant_left(transport, participant, reason):
        await task.queue_frame(EndFrame())

    runner = PipelineRunner()

    await runner.run(task)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipecat Simple ChatBot")
    parser.add_argument("-u", type=str, help="Room URL")
    parser.add_argument("-t", type=str, help="Token")
    parser.add_argument("-i", type=str, help="Call ID")
    config = parser.parse_args()

    try:
        asyncio.run(main(config.u, config.t, config.i))
    except Exception as e:
        logger.error(f"++++++++++++++ Error: {e}")
        sys.exit(1)

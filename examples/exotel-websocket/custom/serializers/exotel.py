from typing import Optional, Dict, Any
import json
import base64
from dataclasses import dataclass

from pydantic import BaseModel
from pipecat.audio.utils import ulaw_to_pcm, pcm_to_ulaw
from pipecat.frames.frames import AudioRawFrame, Frame, StartInterruptionFrame

from pipecat.serializers.base_serializer import FrameSerializer
from pipecat.frames.frames import Frame
from livekit.rtc import AudioFrame


@dataclass
class ExotelFrameSerializer(FrameSerializer):
    class InputParams(BaseModel):
        sample_rate: int = 8000

    def __init__(self, stream_sid: str, params: InputParams = InputParams()):
        self._stream_sid = stream_sid
        self._params = params

    def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, AudioRawFrame):
            data = frame.audio
            # Convert PCM to ULaw for Exotel streaming requirement
            serialized_data = pcm_to_ulaw(
                data, frame.sample_rate, self._params.sample_rate)
            payload = base64.b64encode(serialized_data).decode("utf-8")
            answer = {
                "event": "media",
                "streamSid": self._stream_sid,
                "media": {"payload": payload}
            }
            return json.dumps(answer)
        elif isinstance(frame, StartInterruptionFrame):
            answer = {"event": "clear", "streamSid": self._stream_sid}
            return json.dumps(answer)
        return None

    def deserialize(self, data: str | bytes) -> Frame | None:
        message = json.loads(data)
        if message["event"] != "media":
            return None
        else:
            payload_base64 = message["media"]["payload"]
            payload = base64.b64decode(payload_base64)
            deserialized_data = ulaw_to_pcm(
                payload, self._params.sample_rate, self._params.sample_rate)
            audio_frame = AudioRawFrame(
                audio=deserialized_data, num_channels=1, sample_rate=self._params.sample_rate)
            return audio_frame

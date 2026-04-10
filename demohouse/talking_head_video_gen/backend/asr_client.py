import asyncio
import time
import uuid
import aiohttp
import websockets
import os
import gzip
import struct
import json
import logging
from typing import Any, Dict, Optional

from file_link import local_to_link
from arkitect.utils.binary_protocol import (  # type: ignore
    AUDIO_ONLY_REQUEST,
    NO_SEQUENCE,
    POS_SEQUENCE,
    generate_before_payload,
    generate_header,
    parse_response,
)

logger = logging.getLogger(__name__)


class ASRClient:
    """字节跳动（火山引擎）大模型录音文件识别客户端"""

    def __init__(
            self,
            app_key: str,
            access_key: str,
            obs_key_id: str,
            obs_key_secret: str,
            resource_id: str = "volc.seedasr.auc",
    ):
        """
        初始化 ASR 客户端 (使用新版控制台的鉴权方式)
        :param api_key: 火山引擎控制台获取的 API Key
        :param resource_id: 资源ID，默认使用豆包录音文件识别模型2.0 (volc.seedasr.auc)
        """
        self.app_key = app_key
        self.access_key = access_key
        self.obs_key_id = obs_key_id
        self.obs_key_secret = obs_key_secret
        self.resource_id = resource_id
        self.submit_url = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
        self.query_url = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"

    # TODO: 上传对象存储
    async def asr(self,
                  audio_path: str,
                  audio_format: str,
                  uid: str = "default_user",
                  enable_speaker_info: bool = False,
                  timeout: int = 300,
                  poll_interval: float = 3.0) -> Optional[Dict[str, Any]]:
        """
        提交识别任务并轮询获取结果
        :param audio_url: 音频的公网访问链接
        :param audio_format: 音频格式 (例如: mp3, wav, ogg)
        :param uid: 用户标识 (推荐传 IMEI 或 MAC，这里默认占位)
        :param enable_speaker_info: 是否开启说话人分离
        :param timeout: 轮询超时时间(秒)
        :param poll_interval: 每次轮询的间隔(秒)
        :return: 识别结果字典，包含文本和时间戳分句信息
        """
        # 生成唯一的请求 ID
        task_id = str(uuid.uuid4())

        # ---------------- 1. 提交任务阶段 ----------------
        submit_headers = {
            "X-Api-App-Key": self.app_key,
            "X-Api-Access-Key": self.access_key,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Request-Id": task_id,
            "X-Api-Sequence": "-1",
            "Content-Type": "application/json"
        }
        audio_url = local_to_link(audio_path)

        submit_payload = {
            "user": {
                "uid": uid
            },
            "audio": {
                "url": audio_url,
                "format": audio_format
            },
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,  # 启用文本规范化 (123美元)
                "show_utterances": True,  # 输出分句信息和时间戳，非常重要
                "enable_speaker_info": enable_speaker_info  # 说话人分离
            }
        }

        async with aiohttp.ClientSession() as session:
            logger.debug("[ASR] 正在提交任务, Task ID: %s", task_id)
            async with session.post(self.submit_url, headers=submit_headers, json=submit_payload) as submit_resp:
                # 提交接口的 body 是空的，状态码在 Header 里
                status_code = submit_resp.headers.get("X-Api-Status-Code")
                message = submit_resp.headers.get("X-Api-Message")

                if status_code != "20000000":
                    raise Exception(f"ASR 提交任务失败! 状态码: {status_code}, 信息: {message}")

            # ---------------- 2. 轮询查询阶段 ----------------
            query_headers = {
                "X-Api-App-Key": self.app_key,
                "X-Api-Access-Key": self.access_key,
                "X-Api-Resource-Id": self.resource_id,
                "X-Api-Request-Id": task_id,
                "Content-Type": "application/json"
            }

            start_time = time.time()
            logger.debug("[ASR] 任务提交成功，正在等待服务端转写。")

            while time.time() - start_time < timeout:
                await asyncio.sleep(poll_interval)

                async with session.post(self.query_url, headers=query_headers, json={}) as query_resp:
                    q_status_code = query_resp.headers.get("X-Api-Status-Code")

                    if q_status_code == "20000000":
                        # 处理成功，解析返回的 JSON (包含 result 和 utterances)
                        data = await query_resp.json()
                        logger.debug("[ASR] 转写完成。")
                        return data.get("result")

                    elif q_status_code in ["20000001", "20000002"]:
                        # 20000001: 处理中 / 20000002: 队列中
                        continue

                    elif q_status_code == "20000003":
                        # 静音音频，没有检测到人声
                        logger.warning("[ASR] 检测到静音音频。")
                        return {"text": "", "utterances": []}

                    else:
                        q_message = query_resp.headers.get("X-Api-Message")
                        raise Exception(f"ASR 查询任务报错! 状态码: {q_status_code}, 信息: {q_message}")

            raise TimeoutError(f"ASR 任务处理超时（超过 {timeout} 秒）")


class StreamASRClient:
    """字节跳动（火山引擎）大模型录音文件识别客户端 - 适配底层二进制协议版"""

    def __init__(self, app_key: str, access_key: str, resource_id: str = "volc.bigasr.sauc.duration"):
        self.app_key = app_key
        self.access_key = access_key
        self.resource_id = resource_id
        # 流式识别端点
        self.uri = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"

    async def asr(self,
                  audio_path: str,
                  audio_format: str,
                  uid: str = "default_user",
                  enable_speaker_info: bool = False,
                  timeout: int = 300,
                  poll_interval: float = 3.0) -> Optional[Dict[str, Any]]:
        """
        读取本地音频文件，按照火山的二进制协议拆分发送，并收集最终结果。
        """
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"未找到音频文件: {audio_path}")

        task_id = str(uuid.uuid4())

        # Header 严格遵循你的正确参考
        headers = {
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Access-Key": self.access_key,
            "X-Api-App-Key": self.app_key,
            "X-Api-Request-Id": task_id,
        }

        logger.debug("[StreamASR] 正在连接服务端，任务 ID: %s", task_id)

        try:
            # 建立 WebSocket 连接
            conn = await websockets.connect(
                self.uri,
                additional_headers=headers,
                ping_interval=None,
                ping_timeout=None,
            )
        except Exception as e:
            logger.error("[StreamASR] WebSocket 连接失败: %s", e)
            return None

        final_text = ""
        utterances = []
        is_finished = False

        # ==========================================
        # 1. 握手与配置：发送 FULL_CLIENT_REQUEST
        # ==========================================
        init_payload = {
            "user": {"uid": uid},
            "audio": {"format": audio_format},
            "request": {
                "model_name": "bigmodel",
                "enable_speaker_info": enable_speaker_info,
                "show_utterances": True
            }
        }

        # 将 JSON 序列化并进行 GZIP 压缩
        payload_bytes = gzip.compress(json.dumps(init_payload).encode('utf-8'))

        # 拼装二进制报文头
        full_client_bytes = bytearray(generate_header(message_type_specific_flags=POS_SEQUENCE))
        full_client_bytes.extend(generate_before_payload(sequence=1))
        full_client_bytes.extend((len(payload_bytes)).to_bytes(4, "big"))  # 4字节 payload size
        full_client_bytes.extend(payload_bytes)

        await conn.send(full_client_bytes)

        # 接收初始化响应
        init_res = await conn.recv()
        logger.debug("[StreamASR] 配置帧已发送，初始化成功。")

        # ==========================================
        # 2. 发送任务：后台拆分音频文件并发送 AUDIO_ONLY_REQUEST
        # ==========================================
        async def send_audio_chunks():
            try:
                chunk_size = 4096
                with open(audio_path, "rb") as f:
                    while True:
                        chunk = f.read(chunk_size)
                        if not chunk:
                            break

                        # 压缩音频块并封装二进制头
                        chunk_compressed = gzip.compress(chunk)
                        audio_only_bytes = bytearray(
                            generate_header(message_type=AUDIO_ONLY_REQUEST, message_type_specific_flags=NO_SEQUENCE)
                        )
                        audio_only_bytes.extend(struct.pack(">I", len(chunk_compressed)))
                        audio_only_bytes.extend(chunk_compressed)

                        await conn.send(audio_only_bytes)

                        # 让出事件循环，防止底层 Ping 阻塞引发 1011
                        await asyncio.sleep(0.01)

                # 注：如果流式识别要求通过标志位发送“最后包”信号，你可能需要再组装发送一帧 is_last_package=True 的包
                logger.debug("[StreamASR] 音频数据已全部送达。")

            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error("[StreamASR] 发送音频数据出错: %s", e)

        # 启动发送任务
        sender_task = asyncio.create_task(send_audio_chunks())

        # ==========================================
        # 3. 接收任务：主循环解析服务端返回的二进制响应
        # ==========================================
        try:
            while not is_finished:
                # 设置超时防死锁
                res_bytes = await asyncio.wait_for(conn.recv(), timeout=timeout)

                # 解码二进制返回内容
                parsed_res = parse_response(res_bytes)

                # 从解析后的字典中提取 result
                payload_msg = parsed_res.get("payload_msg", {})
                result_dict = payload_msg.get("result", {})

                # 更新文本和分句
                if "text" in result_dict and result_dict["text"]:
                    final_text = result_dict["text"]
                if "utterances" in result_dict and result_dict["utterances"]:
                    utterances = result_dict["utterances"]

                # 检查服务端是否下发了识别结束的标识
                if parsed_res.get("is_last_package", False):
                    logger.debug("[StreamASR] 收到最终识别包，流式通信结束。")
                    is_finished = True

        except asyncio.TimeoutError:
            logger.error("[StreamASR] 接收结果超时 (%ss)", timeout)
        except websockets.exceptions.ConnectionClosed as e:
            logger.error("[StreamASR] 识别过程中连接关闭: %s", e)
        except Exception as e:
            logger.error("[StreamASR] 解析响应时出错: %s", e)
        finally:
            # 清理动作
            if not sender_task.done():
                sender_task.cancel()
            await conn.close()

        return {
            "text": final_text,
            "utterances": utterances
        }
from __future__ import annotations
"""
Dify API Client - 基于 Dify Service API 源码封装

参考: /Users/yyx/ztqc/car_shiping/ai_pro/dify/api/controllers/service_api/app/

Dify 原始接口:
  POST /v1/workflows/run         - 运行工作流
  POST /v1/chat-messages         - 聊天
  POST /v1/completion-messages   - 补全
  POST /v1/files/upload          - 上传文件
  POST /v1/workflows/tasks/{id}/stop - 停止任务
  GET  /v1/workflows/logs        - 运行日志
"""

import json
import httpx
from typing import AsyncGenerator


class DifyClient:
    """统一的 Dify API 客户端"""

    def __init__(self, base_url: str, api_key: str):
        # 去掉末尾可能存在的 /v1，统一由方法内部拼接
        base_url = base_url.rstrip("/")
        if base_url.endswith("/v1"):
            base_url = base_url[:-3].rstrip("/")
        self.base_url = base_url
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    async def _post(self, url: str, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, headers=self.headers, json=payload)
            if not response.is_success:
                # 保留 Dify 返回的错误信息
                try:
                    error_body = response.json()
                    msg = error_body.get("message", error_body.get("error", str(error_body)))
                except Exception:
                    msg = response.text or f"HTTP {response.status_code}"
                raise RuntimeError(f"Dify 请求失败: {msg} (URL: {url})")
            return response.json()

    async def _post_stream(self, url: str, payload: dict) -> AsyncGenerator[str, None]:
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", url, headers=self.headers, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        yield line[6:]

    async def run_workflow(
        self,
        inputs: dict,
        files: list[dict] | None = None,
        streaming: bool = False,
    ) -> dict | AsyncGenerator[str, None]:
        """运行工作流 — POST /v1/workflows/run"""
        payload = {
            "inputs": inputs,
            "files": files,
            "response_mode": "streaming" if streaming else "blocking",
            "user": "editor-user",
        }
        url = f"{self.base_url}/v1/workflows/run"

        if streaming:
            return self._post_stream(url, payload)
        return await self._post(url, payload)

    async def chat(
        self,
        query: str,
        inputs: dict | None = None,
        conversation_id: str | None = None,
        streaming: bool = False,
    ) -> dict | AsyncGenerator[str, None]:
        """聊天 — POST /v1/chat-messages"""
        payload = {
            "query": query,
            "inputs": inputs or {},
            "response_mode": "streaming" if streaming else "blocking",
            "user": "editor-user",
        }
        if conversation_id:
            payload["conversation_id"] = conversation_id

        url = f"{self.base_url}/v1/chat-messages"
        if streaming:
            return self._post_stream(url, payload)
        return await self._post(url, payload)

    async def completion(
        self,
        inputs: dict,
        streaming: bool = False,
    ) -> dict | AsyncGenerator[str, None]:
        """补全 — POST /v1/completion-messages"""
        payload = {
            "inputs": inputs,
            "response_mode": "streaming" if streaming else "blocking",
            "user": "editor-user",
        }
        url = f"{self.base_url}/v1/completion-messages"
        if streaming:
            return self._post_stream(url, payload)
        return await self._post(url, payload)

    async def get_app_parameters(self) -> dict:
        """获取应用参数定义 — GET /v1/parameters"""
        url = f"{self.base_url}/v1/parameters"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()

    async def get_app_info(self) -> dict:
        """获取应用基本信息 — GET /v1/info"""
        url = f"{self.base_url}/v1/info"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()

    async def upload_file(self, file_content: bytes, filename: str, mimetype: str = "application/octet-stream") -> dict:
        """上传文件 — POST /v1/files/upload"""
        url = f"{self.base_url}/v1/files/upload"
        headers = {k: v for k, v in self.headers.items() if k != "Content-Type"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                headers=headers,
                files={"file": (filename, file_content, mimetype)},
            )
            response.raise_for_status()
            return response.json()

    async def stop_task(self, task_id: str) -> dict:
        """停止任务 — POST /v1/workflows/tasks/{task_id}/stop"""
        url = f"{self.base_url}/v1/workflows/tasks/{task_id}/stop"
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, headers=self.headers)
            response.raise_for_status()
            return response.json()

    async def get_workflow_logs(
        self,
        page: int = 1,
        limit: int = 20,
        status: str | None = None,
    ) -> dict:
        """获取运行日志 — GET /v1/workflows/logs"""
        url = f"{self.base_url}/v1/workflows/logs"
        params = {"page": page, "limit": limit}
        if status:
            params["status"] = status

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            return response.json()

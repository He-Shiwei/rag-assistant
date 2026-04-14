import os
import json
import uuid
import secrets
import hashlib
from datetime import datetime
from typing import Optional, List, Dict, Tuple
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from dashscope import embeddings
from pymongo import MongoClient
from qdrant_client import QdrantClient
from qdrant_client.http import models


class Settings(BaseSettings):
    APP_NAME: str = "RAG智能助手"
    APP_VERSION: str = "1.0.0"
    DASHSCOPE_API_KEY: str = ""
    LLM_MODEL: str = "qwen3-30b-a3b-thinking-2507"
    EMBEDDING_MODEL: str = "text-embedding-v2"
    TEMPERATURE: float = 0.7
    MAX_TOKENS: int = 2000
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 50
    TOP_K: int = 3
    MONGODB_URI: str = ""
    QDRANT_URL: str = ""
    QDRANT_API_KEY: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


mongo_client = None
db = None
users_collection = None
conversations_collection = None
qdrant_client = None

if settings.MONGODB_URI:
    try:
        mongo_client = MongoClient(
            settings.MONGODB_URI,
            tls=True,
            tlsAllowInvalidCertificates=True,
            serverSelectionTimeoutMS=30000,
            connectTimeoutMS=30000
        )
        db = mongo_client["rag_assistant"]
        users_collection = db["users"]
        conversations_collection = db["conversations"]
        users_collection.create_index("username", unique=True)
        print("MongoDB connected successfully")
    except Exception as e:
        print(f"MongoDB connection failed: {e}")

if settings.QDRANT_URL and settings.QDRANT_API_KEY:
    try:
        qdrant_client = QdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY
        )
        collections = qdrant_client.get_collections()
        print(f"Qdrant connected successfully. Collections: {collections}")
    except Exception as e:
        print(f"Qdrant connection failed: {e}")


class Message(BaseModel):
    role: str
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)


class Conversation(BaseModel):
    id: str
    title: str = "新对话"
    messages: List[Message] = []
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class UserCreate(BaseModel):
    username: str
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: str
    username: str
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None


class ChatResponse(BaseModel):
    answer: str
    conversation_id: str
    sources: Optional[List[dict]] = None


class ConversationCreate(BaseModel):
    title: Optional[str] = None


class ConversationListResponse(BaseModel):
    conversations: List[Conversation]


class QueryAnalytics(BaseModel):
    total_queries: int
    frequent_keywords: List[dict]
    recent_queries: List[str]


tokens: Dict[str, str] = {}
documents_store: Dict[int, dict] = {}
CHUNK_SIZE = settings.CHUNK_SIZE
CHUNK_OVERLAP = settings.CHUNK_OVERLAP


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def create_token(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    tokens[token] = user_id
    return token


def verify_token(authorization: Optional[str] = Header(None)) -> Optional[str]:
    if not authorization:
        return None
    if authorization.startswith("Bearer "):
        token = authorization[7:]
    else:
        token = authorization
    return tokens.get(token)


def get_embedding(text: str) -> Optional[List[float]]:
    if not settings.DASHSCOPE_API_KEY:
        return None
    try:
        response = embeddings.call(
            model=settings.EMBEDDING_MODEL,
            input=text
        )
        if response.status_code == 200:
            return response.output['embeddings'][0]['embedding']
        return None
    except Exception as e:
        print(f"Embedding error: {e}")
        return None


def split_text(text: str) -> List[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunk = text[start:end]
        chunks.append(chunk)
        start = end - CHUNK_OVERLAP
    return chunks


def search_documents(query: str, top_k: int = 3) -> List[dict]:
    if not qdrant_client:
        return []
    
    query_embedding = get_embedding(query)
    if not query_embedding:
        return []
    
    try:
        search_result = qdrant_client.search(
            collection_name="knowledge_base",
            query_vector=query_embedding,
            limit=top_k
        )
        
        results = []
        for point in search_result:
            results.append({
                "content": point.payload.get("content", ""),
                "source": point.payload.get("source", "未知"),
                "chunk_id": point.payload.get("chunk_id", 0),
                "score": point.score
            })
        return results
    except Exception as e:
        print(f"Search error: {e}")
        return []


def add_documents_to_qdrant(chunks: List[str], source: str):
    if not qdrant_client:
        return
    
    try:
        qdrant_client.recreate_collection(
            collection_name="knowledge_base",
            vectors_config=models.VectorParams(
                size=1536,
                distance=models.Distance.COSINE
            )
        )
    except:
        pass
    
    points = []
    for i, chunk in enumerate(chunks):
        embedding = get_embedding(chunk)
        if embedding:
            point_id = len(documents_store)
            documents_store[point_id] = {
                "content": chunk,
                "source": source,
                "chunk_id": i
            }
            points.append(models.PointStruct(
                id=point_id,
                vector=embedding,
                payload={
                    "content": chunk,
                    "source": source,
                    "chunk_id": i
                }
            ))
    
    if points:
        qdrant_client.upsert(
            collection_name="knowledge_base",
            points=points
        )


def get_answer(question: str) -> Dict:
    if not qdrant_client:
        return {"answer": "知识库尚未准备就绪，请先上传文档。", "sources": []}
    
    docs = search_documents(question, settings.TOP_K)
    
    if not docs:
        return {"answer": "在知识库中未找到相关信息。", "sources": []}
    
    context = "\n\n".join([doc["content"] for doc in docs])
    
    try:
        import urllib.request
        import urllib.error
        
        url = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {settings.DASHSCOPE_API_KEY}'
        }
        
        prompt = f"""你是一个专业的知识库问答助手，专门帮助用户解答关于文档的问题。
请用专业、友好的语气回答问题。如果知识库中有相关信息，请基于内容回答；如果没有，请说明无法找到相关信息。

背景知识：
{context}

用户问题：{question}

请提供清晰、准确的回答。回答："""
        
        data = json.dumps({
            "model": settings.LLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": settings.TEMPERATURE,
            "max_tokens": settings.MAX_TOKENS
        }).encode('utf-8')
        
        req = urllib.request.Request(url, data=data, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
            answer = result['choices'][0]['message']['content']
            
            return {
                "answer": answer,
                "sources": [
                    {
                        "content": doc["content"][:200] + "..." if len(doc["content"]) > 200 else doc["content"],
                        "source": doc["source"],
                        "chunk_id": doc["chunk_id"]
                    }
                    for doc in docs
                ]
            }
    except Exception as e:
        return {"answer": f"处理问题时出现错误：{str(e)}", "sources": []}


def streaming_answer(question: str):
    if not qdrant_client:
        yield "知识库尚未准备就绪，请先上传文档。"
        return
    
    docs = search_documents(question, settings.TOP_K)
    
    if not docs:
        yield "在知识库中未找到相关信息。"
        return
    
    context = "\n\n".join([doc["content"] for doc in docs])
    
    try:
        import urllib.request
        
        url = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {settings.DASHSCOPE_API_KEY}'
        }
        
        prompt = f"""你是一个专业的知识库问答助手，专门帮助用户解答关于文档的问题。
请用专业、友好的语气回答问题。如果知识库中有相关信息，请基于内容回答；如果没有，请说明无法找到相关信息。

背景知识：
{context}

用户问题：{question}

请提供清晰、准确的回答。回答："""
        
        data = json.dumps({
            "model": settings.LLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": settings.TEMPERATURE,
            "max_tokens": settings.MAX_TOKENS,
            "stream": True
        }).encode('utf-8')
        
        req = urllib.request.Request(url, data=data, headers=headers, method='POST')
        
        with urllib.request.urlopen(req, timeout=60) as response:
            import base64
            for line in response:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    if line.strip() == 'data: [DONE]':
                        break
                    try:
                        chunk_data = json.loads(line[6:])
                        if 'choices' in chunk_data and len(chunk_data['choices']) > 0:
                            delta = chunk_data['choices'][0].get('delta', {})
                            if 'content' in delta:
                                yield delta['content']
                    except:
                        pass
    except Exception as e:
        yield f"处理问题时出现错误：{str(e)}"


@app.get("/")
async def root():
    return {"message": "RAG智能助手 API", "version": "1.0.0"}


@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "mongodb": "connected" if mongo_client else "not configured",
        "qdrant": "connected" if qdrant_client else "not configured"
    }


@app.post("/api/auth/register", response_model=Token)
async def register(user_data: UserCreate):
    if users_collection is None:
        raise HTTPException(status_code=500, detail="数据库未配置")
    
    existing = users_collection.find_one({"username": user_data.username})
    if existing:
        raise HTTPException(status_code=400, detail="用户名已存在")
    
    user_id = str(uuid.uuid4())
    user_doc = {
        "_id": user_id,
        "username": user_data.username,
        "password_hash": hash_password(user_data.password),
        "created_at": datetime.now().isoformat()
    }
    users_collection.insert_one(user_doc)
    
    token = create_token(user_id)
    return Token(
        access_token=token,
        user=UserResponse(
            id=user_id,
            username=user_data.username,
            created_at=datetime.now()
        )
    )


@app.post("/api/auth/login", response_model=Token)
async def login(user_data: UserLogin):
    if users_collection is None:
        raise HTTPException(status_code=500, detail="数据库未配置")
    
    user = users_collection.find_one({
        "username": user_data.username,
        "password_hash": hash_password(user_data.password)
    })
    
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    user_id = user["_id"]
    token = create_token(user_id)
    return Token(
        access_token=token,
        user=UserResponse(
            id=user_id,
            username=user["username"],
            created_at=datetime.fromisoformat(user["created_at"])
        )
    )


@app.get("/api/auth/me", response_model=Optional[UserResponse])
async def get_current_user_info(authorization: Optional[str] = Header(None)):
    user_id = verify_token(authorization)
    if not user_id:
        return None
    
    if users_collection is None:
        return None
    
    user = users_collection.find_one({"_id": user_id})
    if not user:
        return None
    
    return UserResponse(
        id=user["_id"],
        username=user["username"],
        created_at=datetime.fromisoformat(user["created_at"])
    )


@app.post("/api/auth/logout")
async def logout(authorization: Optional[str] = Header(None)):
    if authorization:
        if authorization.startswith("Bearer "):
            token = authorization[7:]
        else:
            token = authorization
        tokens.pop(token, None)
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, authorization: Optional[str] = Header(None)):
    user_id = verify_token(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="请先登录")
    
    conversation_id = request.conversation_id
    
    if conversation_id and conversations_collection:
        conv = conversations_collection.find_one({"_id": conversation_id, "user_id": user_id})
    else:
        conv = None
    
    if not conv:
        conversation_id = str(uuid.uuid4())
        conv_doc = {
            "_id": conversation_id,
            "user_id": user_id,
            "title": "新对话",
            "messages": [],
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        if conversations_collection:
            conversations_collection.insert_one(conv_doc)
    
    message = {
        "role": "user",
        "content": request.message,
        "timestamp": datetime.now().isoformat()
    }
    
    if conversations_collection:
        conversations_collection.update_one(
            {"_id": conversation_id},
            {
                "$push": {"messages": message},
                "$set": {"updated_at": datetime.now().isoformat()}
            }
        )
    
    result = get_answer(request.message)
    
    assistant_message = {
        "role": "assistant",
        "content": result["answer"],
        "timestamp": datetime.now().isoformat()
    }
    
    if conversations_collection:
        conversations_collection.update_one(
            {"_id": conversation_id},
            {
                "$push": {"messages": assistant_message},
                "$set": {"updated_at": datetime.now().isoformat()}
            }
        )
    
    return ChatResponse(
        answer=result["answer"],
        conversation_id=conversation_id,
        sources=result.get("sources")
    )


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest, authorization: Optional[str] = Header(None)):
    user_id = verify_token(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="请先登录")
    
    conversation_id = request.conversation_id
    
    if conversation_id and conversations_collection:
        conv = conversations_collection.find_one({"_id": conversation_id, "user_id": user_id})
    else:
        conv = None
    
    if not conv:
        conversation_id = str(uuid.uuid4())
        conv_doc = {
            "_id": conversation_id,
            "user_id": user_id,
            "title": "新对话",
            "messages": [],
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        if conversations_collection:
            conversations_collection.insert_one(conv_doc)
    
    message = {
        "role": "user",
        "content": request.message,
        "timestamp": datetime.now().isoformat()
    }
    
    if conversations_collection:
        conversations_collection.update_one(
            {"_id": conversation_id},
            {
                "$push": {"messages": message},
                "$set": {"updated_at": datetime.now().isoformat()}
            }
        )
    
    full_answer = []
    
    async def generate():
        for chunk in streaming_answer(request.message):
            full_answer.append(chunk)
            yield f"data: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"
        
        final_answer = "".join(full_answer)
        assistant_message = {
            "role": "assistant",
            "content": final_answer,
            "timestamp": datetime.now().isoformat()
        }
        
        if conversations_collection:
            conversations_collection.update_one(
                {"_id": conversation_id},
                {
                    "$push": {"messages": assistant_message},
                    "$set": {"updated_at": datetime.now().isoformat()}
                }
            )
        
        yield f"data: {json.dumps({'done': True, 'conversation_id': conversation_id}, ensure_ascii=False)}\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/conversations", response_model=ConversationListResponse)
async def list_conversations(authorization: Optional[str] = Header(None)):
    user_id = verify_token(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="请先登录")
    
    if conversations_collection is None:
        return ConversationListResponse(conversations=[])
    
    cursor = conversations_collection.find({"user_id": user_id}).sort("updated_at", -1)
    convs = []
    for conv in cursor:
        convs.append(Conversation(
            id=conv["_id"],
            title=conv.get("title", "新对话"),
            messages=[Message(**msg) for msg in conv.get("messages", [])],
            created_at=datetime.fromisoformat(conv["created_at"]),
            updated_at=datetime.fromisoformat(conv["updated_at"])
        ))
    
    return ConversationListResponse(conversations=convs)


@app.post("/api/conversations", response_model=Conversation)
async def create_conversation(
    conversation: ConversationCreate = None,
    authorization: Optional[str] = Header(None)
):
    user_id = verify_token(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="请先登录")
    
    title = conversation.title if conversation and conversation.title else "新对话"
    conv_id = str(uuid.uuid4())
    
    conv_doc = {
        "_id": conv_id,
        "user_id": user_id,
        "title": title,
        "messages": [],
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }
    
    if conversations_collection:
        conversations_collection.insert_one(conv_doc)
    
    return Conversation(
        id=conv_id,
        title=title,
        messages=[],
        created_at=datetime.now(),
        updated_at=datetime.now()
    )


@app.get("/api/conversations/{conv_id}")
async def get_conversation(conv_id: str, authorization: Optional[str] = Header(None)):
    user_id = verify_token(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="请先登录")
    
    if conversations_collection is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    
    conv = conversations_collection.find_one({"_id": conv_id, "user_id": user_id})
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    
    return Conversation(
        id=conv["_id"],
        title=conv.get("title", "新对话"),
        messages=[Message(**msg) for msg in conv.get("messages", [])],
        created_at=datetime.fromisoformat(conv["created_at"]),
        updated_at=datetime.fromisoformat(conv["updated_at"])
    )


@app.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: str, authorization: Optional[str] = Header(None)):
    user_id = verify_token(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="请先登录")
    
    if conversations_collection:
        result = conversations_collection.delete_one({"_id": conv_id, "user_id": user_id})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="对话不存在")
    
    return {"status": "deleted"}


@app.delete("/api/conversations/{conv_id}/messages")
async def clear_conversation(conv_id: str, authorization: Optional[str] = Header(None)):
    user_id = verify_token(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="请先登录")
    
    if conversations_collection:
        result = conversations_collection.update_one(
            {"_id": conv_id, "user_id": user_id},
            {"$set": {"messages": [], "updated_at": datetime.now().isoformat()}}
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="对话不存在")
    
    return {"status": "cleared"}


@app.get("/api/analytics", response_model=QueryAnalytics)
async def get_analytics(authorization: Optional[str] = Header(None)):
    user_id = verify_token(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="请先登录")
    
    if conversations_collection is None:
        return QueryAnalytics(total_queries=0, frequent_keywords=[], recent_queries=[])
    
    cursor = conversations_collection.find({"user_id": user_id})
    queries = []
    keywords = {}
    
    import re
    for conv in cursor:
        for msg in conv.get("messages", []):
            if msg.get("role") == "user":
                queries.append(msg["content"])
                words = re.findall(r'[\u4e00-\u9fa5a-zA-Z0-9]+', msg["content"].lower())
                for word in words:
                    if len(word) > 1:
                        keywords[word] = keywords.get(word, 0) + 1
    
    frequent = sorted([{"keyword": k, "count": v} for k, v in keywords.items()], key=lambda x: x["count"], reverse=True)[:10]
    
    return QueryAnalytics(
        total_queries=len(queries),
        frequent_keywords=frequent,
        recent_queries=queries[-20:] if len(queries) > 20 else queries
    )


@app.post("/api/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    authorization: Optional[str] = Header(None)
):
    user_id = verify_token(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="请先登录")
    
    if not file.filename.endswith(('.txt', '.md')):
        raise HTTPException(status_code=400, detail="仅支持 .txt 或 .md 文件")
    
    content = await file.read()
    text = content.decode('utf-8')
    
    chunks = split_text(text)
    
    add_documents_to_qdrant(chunks, file.filename)
    
    return {
        "id": str(uuid.uuid4()),
        "filename": file.filename,
        "status": "indexed",
        "chunks": len(chunks)
    }

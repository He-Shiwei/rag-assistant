import os
import json
import uuid
import secrets
import hashlib
from datetime import datetime
from typing import Optional, List, Dict
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableParallel, RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pymongo import MongoClient
from bson import ObjectId


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

if settings.MONGODB_URI:
    try:
        mongo_client = MongoClient(settings.MONGODB_URI)
        db = mongo_client["rag_assistant"]
        users_collection = db["users"]
        conversations_collection = db["conversations"]
        users_collection.create_index("username", unique=True)
        print("MongoDB connected successfully")
    except Exception as e:
        print(f"MongoDB connection failed: {e}")


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
vector_store = None
llm = None
embeddings = None
splitter = RecursiveCharacterTextSplitter(
    chunk_size=settings.CHUNK_SIZE,
    chunk_overlap=settings.CHUNK_OVERLAP,
    length_function=len
)


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


def init_llm():
    global llm
    if not settings.DASHSCOPE_API_KEY:
        return
    os.environ["DASHSCOPE_API_KEY"] = settings.DASHSCOPE_API_KEY
    llm = ChatOpenAI(
        base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
        api_key=settings.DASHSCOPE_API_KEY,
        model=settings.LLM_MODEL,
        temperature=settings.TEMPERATURE,
        max_tokens=settings.MAX_TOKENS,
        streaming=True
    )


def get_answer(question: str) -> Dict:
    if not vector_store:
        return {"answer": "知识库尚未准备就绪，请先上传文档。", "sources": []}
    
    if not llm:
        init_llm()
    
    if not llm:
        return {"answer": "LLM 未配置，请检查 API Key。", "sources": []}
    
    try:
        docs = vector_store.similarity_search(question, k=settings.TOP_K)
        sources = [
            {
                "content": doc.page_content[:200] + "..." if len(doc.page_content) > 200 else doc.page_content,
                "source": doc.metadata.get("source", "未知"),
                "chunk_id": doc.metadata.get("chunk_id", 0)
            }
            for doc in docs
        ]
        
        context = "\n\n".join([doc.page_content for doc in docs])
        
        if not context.strip():
            return {"answer": "在知识库中未找到相关信息。", "sources": []}
        
        template = """你是一个专业的知识库问答助手，专门帮助用户解答关于文档的问题。
请用专业、友好的语气回答问题。如果知识库中有相关信息，请基于内容回答；如果没有，请说明无法找到相关信息。

背景知识：
{context}

用户问题：{question}

请提供清晰、准确的回答。回答："""
        
        prompt = ChatPromptTemplate.from_template(template)
        chain = (
            RunnableParallel({"context": lambda x: context, "question": RunnablePassthrough()})
            | prompt
            | llm
            | StrOutputParser()
        )
        
        answer = chain.invoke(question)
        return {"answer": answer, "sources": sources}
    
    except Exception as e:
        return {"answer": f"处理问题时出现错误：{str(e)}", "sources": []}


def streaming_answer(question: str):
    if not vector_store:
        yield "知识库尚未准备就绪，请先上传文档。"
        return
    
    if not llm:
        init_llm()
    
    if not llm:
        yield "LLM 未配置，请检查 API Key。"
        return
    
    try:
        docs = vector_store.similarity_search(question, k=settings.TOP_K)
        context = "\n\n".join([doc.page_content for doc in docs])
        
        if not context.strip():
            yield "在知识库中未找到相关信息。"
            return
        
        template = """你是一个专业的知识库问答助手，专门帮助用户解答关于文档的问题。
请用专业、友好的语气回答问题。如果知识库中有相关信息，请基于内容回答；如果没有，请说明无法找到相关信息。

背景知识：
{context}

用户问题：{question}

请提供清晰、准确的回答。回答："""
        
        prompt = ChatPromptTemplate.from_template(template)
        chain = (
            RunnableParallel({"context": lambda x: context, "question": RunnablePassthrough()})
            | prompt
            | llm
            | StrOutputParser()
        )
        
        for chunk in chain.stream(question):
            yield chunk
    
    except Exception as e:
        yield f"处理问题时出现错误：{str(e)}"


@app.get("/")
async def root():
    return {"message": "RAG智能助手 API", "version": settings.APP_VERSION}


@app.get("/api/health")
async def health_check():
    mongo_status = "connected" if mongo_client else "not configured"
    return {
        "status": "healthy",
        "mongodb": mongo_status,
        "vector_store_ready": vector_store is not None
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
    
    chunks = splitter.split_text(text)
    
    global vector_store, embeddings
    
    from langchain_core.documents import Document
    
    docs = [
        Document(
            page_content=chunk,
            metadata={"source": file.filename, "chunk_id": i}
        )
        for i, chunk in enumerate(chunks)
    ]
    
    if embeddings is None and settings.DASHSCOPE_API_KEY:
        os.environ["DASHSCOPE_API_KEY"] = settings.DASHSCOPE_API_KEY
        embeddings = DashScopeEmbeddings(
            model=settings.EMBEDDING_MODEL,
            dashscope_api_key=settings.DASHSCOPE_API_KEY
        )
    
    if embeddings is None:
        raise HTTPException(status_code=500, detail="嵌入模型未配置")
    
    from langchain_community.vectorstores import FAISS
    new_vector_store = FAISS.from_documents(documents=docs, embedding=embeddings)
    
    if vector_store is not None:
        vector_store.merge_from(new_vector_store)
    else:
        vector_store = new_vector_store
    
    return {
        "id": str(uuid.uuid4()),
        "filename": file.filename,
        "status": "indexed",
        "chunks": len(chunks)
    }

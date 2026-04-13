# RAG智能助手

基于 FastAPI + LangChain + Vue 3 的全栈 RAG 应用，支持用户认证、知识库问答、对话历史持久化。

## 📂 项目结构

```
RAG-0413/
├── api/                    # Vercel 后端入口
│   └── index.py            # Serverless 函数
├── backend/                # FastAPI 后端（本地开发）
│   ├── __init__.py
│   ├── auth.py             # 用户认证模块
│   ├── chat_history.py     # 对话历史管理
│   ├── config.py           # 配置文件
│   ├── main.py             # FastAPI 主应用
│   ├── models.py           # 数据模型
│   ├── rag.py              # RAG 核心逻辑
│   └── vector_store.py     # 向量数据库管理
├── frontend/               # Vue 3 前端
│   ├── src/
│   │   ├── App.vue         # 主组件
│   │   ├── main.js         # 入口文件
│   │   ├── api.js          # API 接口
│   │   └── styles.css      # 样式文件
│   ├── index.html
│   ├── package.json
│   └── vite.config.js
├── public/                 # Vercel 静态文件（前端打包）
│   ├── index.html
│   └── assets/
├── data/                   # 数据存储目录
│   ├── chat_history/       # 对话历史
│   │   └── {user_id}/     # 每用户独立目录
│   ├── documents/          # 文档存储
│   ├── users.json          # 用户数据
│   └── vector_store/       # 向量数据库
├── .env                    # 环境变量配置
├── .gitignore              # Git 忽略文件
├── vercel.json             # Vercel 配置
├── requirements.txt        # Python 依赖
└── init_vector_store.py   # 向量数据库初始化脚本
```

## 🛠️ 技术栈

- **后端**: FastAPI + Uvicorn
- **前端**: Vue 3 + Vite
- **RAG**: LangChain + FAISS
- **LLM**: 通义千问 (DashScope)

## 🚀 快速开始

### 📦 1. 环境准备

```bash
# 创建虚拟环境
python -m venv venv
# Windows:
venv\Scripts\activate
# 安装后端依赖
pip install -r requirements.txt

# 安装前端依赖
cd frontend
npm install
```

### ⚙️ 2. 配置环境变量

编辑 `.env` 文件:

```env
DASHSCOPE_API_KEY=your-api-key-here
LLM_MODEL=qwen3-30b-a3b-thinking-2507
MONGODB_URI=mongodb+srv://username:password@cluster.xxxxx.mongodb.net/?retryWrites=true&w=majority
```

**MongoDB URI 获取方式：**
1. 注册 [MongoDB Atlas](https://www.mongodb.com/atlas/database)
2. 创建免费集群
3. 点击 Connect → Connect your application
4. 复制连接字符串，将 `<password>` 替换为你的数据库密码

### 🗄️ 3. 初始化向量数据库（首次运行）

```bash
cd D:\8.agent\RAG
python init_vector_store.py
```

### 🔧 4. 启动后端

```bash
cd D:\8.agent\RAG
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### 🎨 5. 启动前端

```bash
cd frontend
npm run dev
```

前端访问: http://localhost:3000
后端API: http://localhost:8000

默认账号: admin
默认密码: admin123

## ✨ 功能特性

### 🔐 用户认证
- 用户注册和登录
- Token 身份验证
- 多用户支持

### 🤖 智能问答
- 基于知识库的 RAG 问答
- 流式响应
- 显示参考来源

### 💬 对话历史
- 多会话管理
- 每用户独立存储
- 随时切换历史对话

### 📊 FAQ 优化
- 分析用户高频问题
- 构建 FAQ 关键词
- 优化检索效果

## 🔗 API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/auth/register` | POST | 用户注册 |
| `/api/auth/login` | POST | 用户登录 |
| `/api/auth/me` | GET | 获取当前用户 |
| `/api/auth/logout` | POST | 用户登出 |
| `/api/chat` | POST | 发送消息 |
| `/api/chat/stream` | POST | 流式响应 |
| `/api/conversations` | GET | 获取对话列表 |
| `/api/conversations` | POST | 创建对话 |
| `/api/vector-store/rebuild` | POST | 重建索引 |
| `/api/analytics` | GET | 查询分析统计 |

## ☁️ 部署到 Vercel

无需服务器、无需备案，将问答助手部署到 Vercel 免费托管平台。

### 📋 整体思路

把前端打包成静态网页，后端改成一个特殊的入口文件，再配合路由配置文件，一起推送到 GitHub，让 Vercel 自动部署。最终获得 `https://项目名.vercel.app` 的网址。

### 1️⃣ 准备工作

- 注册 GitHub 账号（存放代码）
- 用 GitHub 账号登录 [Vercel 官网](https://vercel.com)
- 电脑安装 Node.js（打包前端）和 Git（上传代码）
- 确保前端项目能正常 `npm run build`

### 2️⃣ 改造后端

创建 `api/index.py` 文件，将 FastAPI 的 `app` 对象放进去：

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 保留原有所有路由...
```

**注意**: Vercel 函数是无状态的，不能依赖本地文件存储数据。如需保存问答记录，需改用云数据库（如 MongoDB Atlas、Supabase）。

### 3️⃣ 创建依赖文件

在项目根目录创建 `requirements.txt`：

```
fastapi
uvicorn
python-multipart
dashscope
langchain
langchain-community
faiss-cpu
```

### 4️⃣ 打包前端

```bash
cd frontend
npm run build
```

将生成的 `dist` 文件夹重命名为 `public`。

### 5️⃣ 创建 Vercel 配置

在根目录创建 `vercel.json`：

```json
{
  "rewrites": [
    { "source": "/api/(.*)", "destination": "/api/index.py" },
    { "source": "/(.*)", "destination": "/public/index.html" }
  ],
  "buildCommand": "echo 'Static site'",
  "outputDirectory": "public"
}
```

### 6️⃣ 整理文件夹结构

```
├── api/
│   └── index.py          # 改造后的后端
├── public/                # 前端打包文件
├── requirements.txt
└── vercel.json
```

可选：创建 `.gitignore` 文件忽略 `__pycache__`、`node_modules` 等。

### 7️⃣ 修改前端 API 地址

将前端中写死的 `http://localhost:8000` 改为相对路径：

```javascript
// 修改前
axios.post('http://localhost:8000/api/ask')

// 修改后
axios.post('/api/ask')
```

### 8️⃣ 上传到 GitHub

- 在 GitHub 新建仓库
- 推送代码，或直接在网页端拖拽上传整个文件夹

### 9️⃣ Vercel 部署

1. 登录 Vercel，点击 "Add New" → "Project"
2. 选择上传的 GitHub 仓库
3. 在 "Environment Variables" 中添加以下变量：
   - `DASHSCOPE_API_KEY` = 你的通义千问 API Key
   - `LLM_MODEL` = qwen3-30b-a3b-thinking-2507
   - `MONGODB_URI` = 你的 MongoDB Atlas 连接字符串
4. 点击 "Deploy"，等待 1-2 分钟
5. 获得域名：`https://项目名.vercel.app`

### 🔧 常见问题

| 问题 | 解答 |
|------|------|
| 用户数据和对话历史会丢吗？ | 已配置 MongoDB Atlas，数据永久保存 |
| API 调用会超时吗？ | OpenAI 等接口通常 2-5 秒返回，Vercel 免费版限制 10 秒，一般没问题 |
| 免费额度够用吗？ | 每月 100GB 流量，个人测试完全够用 |
| 向量知识库会丢吗？ | 服务器休眠后需重新上传文档，如需持久化可接入 Qdrant Cloud |

### ⚡ 你需要动手做的事

1. 前端打包成 `dist`，改名为 `public`
2. 后端代码放进 `api/index.py`，去掉启动部分
3. 创建 `requirements.txt` 和 `vercel.json`
4. 推送到 GitHub
5. Vercel 导入仓库，点 Deploy
6. 拿到域名，发给朋友

---

## ☁️ 上传到 GitHub

### 📁 需要上传的文件

```
├── api/
│   └── index.py            # Serverless 后端
├── frontend/src/            # Vue 前端源码
├── public/                 # 前端打包文件
│   ├── index.html
│   └── assets/
├── .gitignore              # Git 忽略配置
├── README.md               # 项目文档
├── requirements.txt        # Python 依赖
└── vercel.json             # Vercel 配置
```

### ❌ 不需要上传

- `.env` - 包含 API Key（已在 .gitignore 中排除）
- `backend/` - 代码已合并到 api/index.py
- `data/` - 用户数据
- `node_modules/` - npm 依赖
- `.venv/` - Python 虚拟环境

### 🚀 上传步骤

**方法一：网页上传（推荐新手）**

1. 打开 https://github.com/new
2. 仓库名称填：`rag-assistant`
3. 选择 **Public**
4. 点击 **Create repository**
5. 点击 **uploading an existing file**
6. 把上面的 6 个文件/文件夹拖进去上传

**方法二：Git 命令行**

```bash
cd D:\8.agent\RAG-0413

# 初始化 Git
git init

# 添加文件（只添加需要上传的）
git add api public frontend/src .gitignore README.md requirements.txt vercel.json

# 提交
git commit -m "RAG智能助手 Vercel部署版本"

# 添加远程仓库（替换为你的仓库地址）
git remote add origin https://github.com/你的用户名/rag-assistant.git

# 推送
git push -u origin master
```

---

## 🛠️ 开发说明

### 📄 添加新的文档
将 .txt 或 .md 文件放入 `data/documents/` 目录，然后调用重建索引接口：
```bash
POST /api/vector-store/rebuild
```

### 🔧 自定义 LLM
修改 `config.py` 中的 `LLM_MODEL` 配置。

### 🗃️ 修改向量数据库
目前使用 FAISS，如需更换可在 `vector_store.py` 中修改。

### 🌐 内网穿透（可选）
使用 natapp 进行内网穿透：
```bash
cmd 里面切换路径：cd /d D:\8.agent\natapp
然后输入以下命令：
# Windows
natapp.exe -authtoken=75eb55b109401a21
```
穿透的网址为：http://e963f885.natappfree.cc

## 📝 修改日志

### 📅 2026-04-13 界面和输出格式优化

#### 🎨 1. AI输出格式优化 (`frontend/src/App.vue`)

**🔧 formatMessage 函数增强:**
- `###` 标题 → `◈ 标题` (大标题样式，底部加下划线)
- `##` 子标题 → `◆ 子标题`
- `【】` 标题 → `◈ 标题`
- `**加粗**` → 高亮加粗显示
- `- ` 列表 → `• ` 带圆点列表
- `1.` 列表 → 数字列表保留
- `──` 分隔线 → `━━━━` 居中分隔线

**🎨 样式 (`frontend/src/styles.css`):**
- `.msg-heading`: 大标题，1.05rem，加粗，底部2px边框
- `.msg-subheading`: 子标题，0.98rem，次级加粗
- `.msg-strong`: 加粗文字高亮
- `.msg-list`: 带圆点列表项
- `.msg-divider`: 居中分隔线

#### 📐 2. 侧边栏布局调整 (`frontend/src/App.vue`)

**🎯 新增顶部品牌区:**
- 左侧: RAG + 机器人图标 (`fa-robot`)
- 右侧: 隐藏侧边栏按钮 (`fa-chevron-left`)
- 布局类似 DeepSeek 风格

**🔄 按钮位置调整:**
- 隐藏侧边栏按钮从 chat-header 移至 sidebar-header 顶部
- 开启新对话按钮下移
- 整体布局更紧凑

#### 🚀 3. 启动命令

**⚡ 后端:**
```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

**🎨 前端:**
```bash
cd frontend
npm run dev
```

**🔑 默认账号:**
- admin / admin123
- hsw / 123456
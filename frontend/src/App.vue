<template>
  <div class="app">
    <div v-if="!isLoggedIn" class="login-page">
      <div class="login-box">
        <div class="login-logo">
          <i class="fas fa-brain"></i>
        </div>
        <h1>RAG 智能助手</h1>
        <p class="login-subtitle">基于知识库的智能问答系统</p>
        
        <div class="login-tabs">
          <button 
            :class="{ active: loginMode === 'login' }" 
            @click="loginMode = 'login'"
          >登录</button>
          <button 
            :class="{ active: loginMode === 'register' }" 
            @click="loginMode = 'register'"
          >注册</button>
        </div>

        <form @submit.prevent="handleAuth">
          <div class="input-group">
            <i class="fas fa-user"></i>
            <input 
              v-model="authForm.username" 
              type="text" 
              placeholder="用户名"
              required
            />
          </div>
          <div class="input-group">
            <i class="fas fa-lock"></i>
            <input 
              v-model="authForm.password" 
              type="password" 
              placeholder="密码"
              required
            />
          </div>
          <button type="submit" class="login-btn" :disabled="authLoading">
            {{ authLoading ? '处理中...' : (loginMode === 'login' ? '登录' : '注册') }}
          </button>
        </form>
        <p v-if="authError" class="error-msg">{{ authError }}</p>
      </div>
    </div>

    <template v-else>
      <aside class="sidebar" id="sidebar">
        <div class="sidebar-header">
          <div class="sidebar-top-bar">
            <div class="brand-logo">
              <i class="fas fa-robot"></i>
              <span>RAG</span>
            </div>
            <button class="hide-sidebar-btn" @click="toggleSidebar" title="隐藏侧边栏">
              <i class="fas fa-chevron-left"></i>
            </button>
          </div>
          <button class="new-chat-btn" @click="createNewChat">
            <i class="fas fa-plus-circle"></i> 开启新对话
          </button>
        </div>

        <div class="history-title">
          <i class="far fa-comment-dots"></i> 聊天记录
        </div>

        <div class="conversation-list">
          <div
            v-for="conv in conversations"
            :key="conv.id"
            class="conversation-item"
            :class="{ active: currentConversationId === conv.id }"
            @click="switchConversation(conv.id)"
          >
            <span class="conv-title">{{ conv.title || '新对话' }}</span>
            <button class="delete-conv" @click.stop="deleteConversation(conv.id)">
              <i class="fas fa-trash-alt"></i>
            </button>
          </div>
        </div>

        <div class="sidebar-footer">
          <div class="user-info">
            <i class="fas fa-user-circle"></i>
            <span>{{ currentUser?.username }}</span>
          </div>
          <button class="logout-btn" @click="handleLogout">
            <i class="fas fa-sign-out-alt"></i>
          </button>
        </div>
      </aside>

      <main class="chat-main">
        <div class="chat-header">
          <div class="menu-toggle" id="toggleSidebarBtn" @click="toggleSidebar">
            <i class="fas fa-bars"></i>
          </div>
          <h2>
            <i class="fas fa-sparkles"></i>
            <span>{{ currentConversation?.title || '新对话' }}</span>
          </h2>
          <div class="header-actions">
            <button class="header-btn" @click="clearCurrentMessages">
              <i class="fas fa-trash-alt"></i> 清空
            </button>
          </div>
        </div>

        <div class="messages-area" ref="messagesArea">
          <div v-if="!currentConversation?.messages?.length" class="welcome-placeholder">
            <i class="fas fa-sparkles"></i>
            <h3>RAG 智能助手</h3>
            <p>你好！我是基于知识库的智能问答助手。<br>开始提问吧～</p>
          </div>

          <div v-else>
            <div 
              v-for="(msg, idx) in currentConversation?.messages" 
              :key="idx" 
              class="message" 
              :class="msg.role === 'user' ? 'user-message' : 'assistant-message'"
            >
              <div class="message-avatar">
                <i :class="msg.role === 'user' ? 'fas fa-user' : 'fas fa-sparkles'"></i>
              </div>
              <div class="message-content" v-html="formatMessage(msg.content)"></div>
            </div>

            <div v-if="isTyping" class="message assistant-message">
              <div class="message-avatar">
                <i class="fas fa-sparkles"></i>
              </div>
              <div class="message-content thinking-bubble">
                <div class="thinking-dots">
                  <span></span><span></span><span></span>
                </div>
                <div class="thinking-text">AI 正在思考...</div>
              </div>
            </div>
          </div>
        </div>

        <div class="input-container">
          <div class="input-wrapper">
            <textarea
              v-model="inputMessage"
              class="message-input"
              placeholder="发送消息... (Enter 发送，Shift+Enter 换行)"
              rows="1"
              @keydown.enter.exact.prevent="sendMessage"
              @input="autoResize"
            ></textarea>
            <button class="send-btn" @click="sendMessage" :disabled="isTyping || !inputMessage.trim()">
              <i class="fas fa-arrow-up"></i>
            </button>
          </div>
          <div class="doc-hint">
            <i class="fas fa-book"></i> 知识库已加载，可以开始提问
          </div>
        </div>
      </main>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { api } from './api'

const isLoggedIn = ref(false)
const currentUser = ref(null)
const loginMode = ref('login')
const authForm = ref({ username: '', password: '' })
const authLoading = ref(false)
const authError = ref('')

const conversations = ref([])
const currentConversationId = ref(null)
const inputMessage = ref('')
const isTyping = ref(false)
const messagesArea = ref(null)

const currentConversation = computed(() => {
  return conversations.value.find(c => c.id === currentConversationId.value)
})

async function handleAuth() {
  authError.value = ''
  authLoading.value = true
  try {
    if (loginMode.value === 'login') {
      await api.login(authForm.value.username, authForm.value.password)
    } else {
      await api.register(authForm.value.username, authForm.value.password)
    }
    await loadCurrentUser()
    await loadConversations()
    isLoggedIn.value = true
    authForm.value = { username: '', password: '' }
  } catch (e) {
    authError.value = e.message
  } finally {
    authLoading.value = false
  }
}

async function handleLogout() {
  await api.logout()
  isLoggedIn.value = false
  currentUser.value = null
  conversations.value = []
  currentConversationId.value = null
}

async function loadCurrentUser() {
  currentUser.value = await api.getCurrentUser()
}

async function loadConversations() {
  try {
    const data = await api.get('/conversations')
    conversations.value = data.conversations || []
    if (conversations.value.length > 0 && !currentConversationId.value) {
      currentConversationId.value = conversations.value[0].id
    }
  } catch (e) {
    if (conversations.value.length === 0) {
      await createNewChat()
    }
  }
}

async function createNewChat() {
  try {
    const conv = await api.post('/conversations', { title: '新对话' })
    conversations.value.unshift(conv)
    currentConversationId.value = conv.id
  } catch (e) {
    console.error('Failed to create conversation:', e)
  }
}

async function switchConversation(convId) {
  currentConversationId.value = convId
  await api.post(`/conversations/${convId}/switch`)
  scrollToBottom()
}

async function deleteConversation(convId) {
  try {
    await api.delete(`/conversations/${convId}`)
    conversations.value = conversations.value.filter(c => c.id !== convId)
    if (currentConversationId.value === convId) {
      if (conversations.value.length > 0) {
        currentConversationId.value = conversations.value[0].id
      } else {
        await createNewChat()
      }
    }
  } catch (e) {
    console.error('Failed to delete conversation:', e)
  }
}

async function clearCurrentMessages() {
  if (!currentConversationId.value) return
  try {
    await api.delete(`/conversations/${currentConversationId.value}/messages`)
    const conv = conversations.value.find(c => c.id === currentConversationId.value)
    if (conv) conv.messages = []
  } catch (e) {
    console.error('Failed to clear messages:', e)
  }
}

async function sendMessage() {
  if (!inputMessage.value.trim() || isTyping.value) return

  const message = inputMessage.value.trim()
  inputMessage.value = ''

  const conv = conversations.value.find(c => c.id === currentConversationId.value)
  if (conv) {
    if (!conv.messages) conv.messages = []
    conv.messages.push({ role: 'user', content: message })
  }

  if (conv?.title === '新对话') {
    conv.title = message.substring(0, 28) || '新对话'
  }

  scrollToBottom()
  isTyping.value = true

  try {
    let fullAnswer = ''

    for await (const chunk of api.streamChat(message, currentConversationId.value)) {
      if (chunk.done) {
        break
      }
      if (chunk.content) {
        fullAnswer += chunk.content
        if (conv) {
          if (conv.messages[conv.messages.length - 1]?.role === 'assistant') {
            conv.messages[conv.messages.length - 1].content = fullAnswer
          } else {
            conv.messages.push({ role: 'assistant', content: fullAnswer })
          }
        }
        scrollToBottom()
      }
    }
  } catch (e) {
    console.error('Chat error:', e)
    if (conv) {
      conv.messages.push({
        role: 'assistant',
        content: `抱歉，发生了错误：${e.message}`
      })
    }
  }

  isTyping.value = false
  scrollToBottom()
}

function formatMessage(content) {
  if (!content) return ''
  
  let result = content
  
  result = result.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>')
  result = result.replace(/`([^`]+)`/g, '<code>$1</code>')
  
  result = result.replace(/^###\s+(.+)$/gm, '<div class="msg-heading">◈ $1</div>')
  result = result.replace(/^##\s+(.+)$/gm, '<div class="msg-subheading">◆ $1</div>')
  
  result = result.replace(/^【(.+?)】/gm, '<div class="msg-heading">◈ $1</div>')
  
  result = result.replace(/^\*\*([^*]+)\*\*$/gm, '<strong class="msg-strong">$1</strong>')
  
  result = result.replace(/^(-\s+.+)$/gm, '<div class="msg-list">• $1</div>')
  result = result.replace(/^(\d+\.\s+.+)$/gm, '<div class="msg-list-num">$1</div>')
  
  result = result.replace(/^(─{3,})$/gm, '<div class="msg-divider">━━━━</div>')
  
  result = result.replace(/\n/g, '<br>')
  
  return result
}

function scrollToBottom() {
  nextTick(() => {
    if (messagesArea.value) {
      messagesArea.value.scrollTop = messagesArea.value.scrollHeight
    }
  })
}

function autoResize(event) {
  const textarea = event.target
  textarea.style.height = 'auto'
  textarea.style.height = Math.min(120, textarea.scrollHeight) + 'px'
}

function toggleSidebar() {
  const sidebar = document.getElementById('sidebar')
  sidebar.classList.toggle('collapsed')
}

onMounted(async () => {
  const user = await api.getCurrentUser()
  if (user) {
    currentUser.value = user
    await loadConversations()
    isLoggedIn.value = true
  }

  window.addEventListener('auth:logout', () => {
    isLoggedIn.value = false
    currentUser.value = null
    conversations.value = []
    currentConversationId.value = null
  })
})
</script>

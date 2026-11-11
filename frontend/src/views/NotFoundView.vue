<template>
  <main class="empty-state">
    <h1>页面不存在</h1>
    <p class="not-found-hint">链接可能已经失效，或者这份行程被删除了。</p>
    <a-button type="primary" @click="router.push('/')">返回首页</a-button>
  </main>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

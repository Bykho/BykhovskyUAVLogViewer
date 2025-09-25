<template>
    <div class="chat-view">
        <h3>Chat with your logs</h3>
        <p v-if="loading">Loading...</p>
        <p v-else>{{ message }}</p>
    </div>
</template>

<script>
export default {
    name: 'ChatView',
    data () {
        return {
            message: '',
            loading: true
        }
    },
    async mounted () {
        try {
            const response = await fetch('http://localhost:8000/chat')
            const data = await response.json()
            this.message = data.message
            this.loading = false
        } catch (error) {
            this.message = 'Error connecting to backend'
            this.loading = false
        }
    }
}
</script>

<style scoped>
.chat-view {
    padding: 20px;
}
</style>

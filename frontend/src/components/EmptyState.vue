<script setup lang="ts">
withDefaults(defineProps<{ title: string; note?: string }>(), { note: '' })
</script>

<template><div class="empty"><strong>{{ title }}</strong><span>{{ note }}</span></div></template>

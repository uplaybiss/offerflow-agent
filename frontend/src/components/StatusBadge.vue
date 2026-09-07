<script setup lang="ts">
defineProps<{ value: string }>()
</script>

<template><span class="status" :data-status="value">{{ value }}</span></template>

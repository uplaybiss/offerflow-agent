<script setup lang="ts">
import { labelFor } from '../uiLabels'
defineProps<{ value: string }>()
</script>

<template><span class="status" :data-status="value">{{ labelFor(value) }}</span></template>

export const UI_LABELS: Record<string, string> = {
  PLANNED: '准备投递', APPLIED: '已投递', ASSESSMENT: '笔试 / 测评', INTERVIEW: '面试',
  OFFER: 'Offer', REJECTED: '已淘汰', WITHDRAWN: '已放弃',
  ACTIVE: '招聘中', EXPIRED: '已截止', CLOSED: '已关闭', ARCHIVED: '已归档',
  GENERAL: '普通待办', APPLICATION: '投递', MATERIAL: '材料准备', FOLLOW_UP: '跟进',
  P1: '紧急', P2: '普通', P3: '低',
  TODO: '待处理', IN_PROGRESS: '进行中', DONE: '已完成', COMPLETED: '已完成', CANCELLED: '已取消',
  SCHEDULED: '已安排', TECHNICAL: '技术面试', HR: 'HR 面试', MANAGER: '主管面试', OTHER: '其他',
  MANUAL: '手工创建', AI_TAILORED: 'AI 建议后保存', SUGGESTED: '建议后保存',
  APPLICATION_TRANSITION: '投递阶段更新', INTERVIEW_PROGRESSION: '下一轮面试', TASK_CREATE: '创建待办',
  STRONG_MATCH: '高度匹配', MATCH: '基本匹配', WEAK_MATCH: '匹配较弱', NOT_RECOMMENDED: '暂不建议',
  PASS: '满足', FAIL: '不满足', UNKNOWN: '待确认',
  SUPPORTED: '事实已支持', NEEDS_USER_REVIEW: '需要你核对', UNSUPPORTED: '缺少事实依据',
}

export const labelFor = (value: string) => UI_LABELS[value] || value

export const APPLICATION_ORDER = ['PLANNED', 'APPLIED', 'ASSESSMENT', 'INTERVIEW', 'OFFER', 'REJECTED', 'WITHDRAWN']

export const TASK_TYPES = ['GENERAL', 'APPLICATION', 'ASSESSMENT', 'INTERVIEW', 'MATERIAL', 'FOLLOW_UP']
export const TASK_PRIORITIES = ['P1', 'P2', 'P3']
export const TASK_STATUSES = ['TODO', 'IN_PROGRESS', 'DONE', 'CANCELLED']
export const JOB_STATUSES = ['ACTIVE', 'EXPIRED', 'CLOSED', 'ARCHIVED']
export const INTERVIEW_TYPES = ['ASSESSMENT', 'TECHNICAL', 'HR', 'MANAGER', 'OTHER']
export const INTERVIEW_STATUSES = ['PLANNED', 'SCHEDULED', 'COMPLETED', 'CANCELLED']

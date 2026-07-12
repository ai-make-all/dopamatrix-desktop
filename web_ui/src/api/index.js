import axios from 'axios'
import { API_BASE } from '../stores/appStore'

const REVIEW_TARGET_STATUSES = new Set([
  'PENDING',
  'APPROVED',
  'REJECTED',
  'DELETED',
])

export async function updateVideoStatus(hashes, targetStatus) {
  const hashArray = [...new Set(
    (Array.isArray(hashes) ? hashes : [hashes]).filter(Boolean)
  )]
  if (hashArray.length === 0) {
    return {
      message: 'success',
      updated_count: 0,
      target_status: targetStatus,
      updated_hashes: [],
    }
  }
  if (!REVIEW_TARGET_STATUSES.has(targetStatus)) {
    throw new Error(`Unsupported variant status: ${targetStatus}`)
  }

  const response = await axios.post(`${API_BASE}/api/v1/approval/batch-update`, {
    hashes: hashArray,
    target_status: targetStatus,
  })
  return response.data
}

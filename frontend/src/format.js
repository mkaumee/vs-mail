export const CATEGORY_LABELS = {
  BL_COMPARISON: 'Document checks',
  SI_REQUEST: 'Document requests',
  INVOICE_QUERY: 'Invoice queries',
  GENERAL: 'General',
  SPAM: 'Spam',
}

// What a wrong value actually costs. Consignee and notify party carry legal
// title to the cargo; gross weight is a SOLAS declaration.
export const FIELD_LABELS = {
  shipper: 'Shipper',
  consignee: 'Consignee',
  notify_party: 'Notify party',
  port_of_loading: 'Port of loading',
  port_of_discharge: 'Port of discharge',
  container_count: 'Containers',
  gross_weight_kg: 'Gross weight',
}

export const REVIEW_REASONS = {
  wrong_doc_type: 'Wrong document attached',
  missing_attachment: 'Attachment missing',
  unreadable: 'File will not open',
  missing_value: 'A required value is blank',
}

export const statusTone = (result) => {
  if (result.status === 'MISMATCH') return 'defect'
  if (result.status === 'NEEDS_REVIEW') return 'review'
  if (result.concerns?.length) return 'uncertain'
  return 'clean'
}

export const relative = (iso) => {
  if (!iso) return 'never'
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`
  return `${Math.floor(seconds / 86400)} d ago`
}

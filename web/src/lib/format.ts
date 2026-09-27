export const formatDate = (iso: string | null | undefined) => (iso ? iso.slice(0, 16).replace('T', ' ') : '—')

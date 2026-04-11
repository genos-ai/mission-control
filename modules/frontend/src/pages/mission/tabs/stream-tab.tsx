import ConsolePage from '@/pages/mission/console'

// Stream tab — reuses ConsolePage verbatim.
// The ConsolePage reads from the shared MissionStreamContext provided
// by MissionLayout, so no second SSE connection is opened.
export default function StreamTab() {
  return <ConsolePage />
}

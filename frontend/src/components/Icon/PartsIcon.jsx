import { GoCpu } from "react-icons/go";
import { BsGpuCard } from "react-icons/bs";
import { BsMotherboard } from "react-icons/bs";
import { RiRam2Line } from "react-icons/ri";


// SVG icon per part type
export const ICONS = {
  cpu: (
    <GoCpu />
  ),
  gpu: (
    <BsGpuCard/>
  ),
  mb: (
    <BsMotherboard/>
  ),
  ram: (
    <RiRam2Line/>
  ),
  ssd: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="6" width="20" height="12" rx="2" />
      <circle cx="17" cy="12" r="2" />
      <line x1="6" y1="10" x2="12" y2="10" /><line x1="6" y1="14" x2="10" y2="14" />
    </svg>
  ),
  psu: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="7" width="20" height="10" rx="2" />
      <polyline points="13 10 11 14 13 14 11 18" />
      <circle cx="7" cy="12" r="1.5" />
    </svg>
  ),
  case: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="5" y="2" width="14" height="20" rx="2" />
      <line x1="9" y1="7" x2="15" y2="7" />
      <circle cx="12" cy="17" r="1.5" />
    </svg>
  ),
  cooler: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
    </svg>
  ),
  default: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2" />
    </svg>
  ),
}

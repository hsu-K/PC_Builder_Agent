import { useState } from 'react'
import { HiOutlineTemplate } from 'react-icons/hi'
import { MdOutlineGames, MdOutlineWork, MdOutlineAttachMoney, MdOutlineVideoLibrary, MdOutlineTune } from 'react-icons/md'
import styles from './TemplatePanel.module.css'

const PRESET_TEMPLATES = [
  {
    category: '電競',
    icon: <MdOutlineGames size={13} />,
    items: [
      { label: '高效能電競', text: '我想建一台高效能電競電腦，主要用來玩 4K 畫質的 3A 大作，預算約 NT$80,000。' },
      { label: '入門電競',   text: '我想建一台入門電競電腦，玩 1080p 遊戲為主，預算 NT$30,000 以內。' },
    ]
  },
  {
    category: '工作',
    icon: <MdOutlineWork size={13} />,
    items: [
      { label: '程式開發',    text: '我需要一台適合軟體開發的工作站，需要跑多個虛擬機和 Docker，預算 NT$50,000。' },
      { label: 'AI 模型訓練', text: '我需要一台用於 AI 模型訓練的電腦，GPU 效能優先，預算 NT$100,000。' },
    ]
  },
  {
    category: '創作',
    icon: <MdOutlineVideoLibrary size={13} />,
    items: [
      { label: '影片剪輯', text: '我需要一台 4K 影片剪輯工作站，需要流暢跑 Premiere Pro 和 After Effects，預算 NT$60,000。' },
      { label: '3D 建模',  text: '我需要一台適合 Blender 3D 建模的電腦，需要強力 CPU 和 GPU，預算 NT$70,000。' },
    ]
  },
  {
    category: '預算',
    icon: <MdOutlineAttachMoney size={13} />,
    items: [
      { label: '最省預算',  text: '請幫我在 NT$15,000 以內建一台可以日常使用的電腦。' },
      { label: 'CP 值優先', text: '請幫我建一台 CP 值最高的電腦，預算 NT$25,000，用途是文書和輕度遊戲。' },
    ]
  },
]

const USAGE_OPTIONS   = ['電競', '影片剪輯', '3D 建模', 'AI 訓練', '程式開發', '文書辦公', '日常使用']
const BRAND_OPTIONS   = ['Intel CPU', 'AMD CPU', 'NVIDIA GPU', 'AMD GPU', 'ASUS', 'MSI', 'Gigabyte', '不限']
const PRIORITY_OPTIONS = ['效能優先', 'CP 值優先', '靜音優先', '體積優先', '外觀優先']

// 通用模板表單的預設值
const DEFAULT_FORM = {
  usage: '',
  budget: '',
  resolution: '',
  brand: [],
  priority: '',
  extra: '',
}

export default function TemplatePanel({ onSelect, onSavePreference }) {
  const [tab, setTab] = useState('custom')   // 'custom' | 'preset'
  const [form, setForm] = useState(DEFAULT_FORM)

  const toggleBrand = (brand) => {
    setForm(prev => ({
      ...prev,
      brand: prev.brand.includes(brand)
        ? prev.brand.filter(b => b !== brand)
        : [...prev.brand, brand]
    }))
  }

  const buildText = () => {
    const parts = []
    if (form.usage)      parts.push(`用途：${form.usage}`)
    if (form.resolution) parts.push(`目標解析度：${form.resolution}`)
    if (form.budget)     parts.push(`預算：NT$${form.budget}`)
    if (form.brand.length) parts.push(`偏好品牌：${form.brand.join('、')}`)
    if (form.priority)   parts.push(`優先考量：${form.priority}`)
    if (form.extra)      parts.push(`其他需求：${form.extra}`)

    if (parts.length === 0) return ''
    //return `請幫我規劃一台電腦，條件如下：\n${parts.map(p => `- ${p}`).join('\n')}`
    return `${parts.map(p => `- ${p}`).join('\n')}`
  }

  const handleApply = () => {
    const text = buildText()
    if (text) {
      //onSelect(text)
      alert("已設定偏好設定：\n\n" + text)
      onSavePreference?.(form)
    }
  }

  const preview = buildText()

  return (
    <div className={styles.panel}>

      {/* Header + Tab */}
      <div className={styles.header}>
        <div className={styles.headerTitle}>
          <HiOutlineTemplate size={13} />
          <span>需求模板</span>
        </div>
        <div className={styles.tabs}>
          <button
            className={`${styles.tab} ${tab === 'custom' ? styles.tabActive : ''}`}
            onClick={() => setTab('custom')}
          >
            <MdOutlineTune size={12} /> 通用模板
          </button>
          <button
            className={`${styles.tab} ${tab === 'preset' ? styles.tabActive : ''}`}
            onClick={() => setTab('preset')}
          >
            快速選擇
          </button>
        </div>
      </div>

      {/* 通用模板 */}
      {tab === 'custom' && (
        <div className={styles.customBody}>

          {/* 用途 */}
          <div className={styles.field}>
            <label className={styles.fieldLabel}>用途</label>
            <div className={styles.chipGroup}>
              {USAGE_OPTIONS.map(u => (
                <button
                  key={u}
                  className={`${styles.chip} ${form.usage === u ? styles.chipActive : ''}`}
                  onClick={() => setForm(prev => ({ ...prev, usage: prev.usage === u ? '' : u }))}
                >
                  {u}
                </button>
              ))}
            </div>
          </div>

          {/* 預算 */}
          <div className={styles.field}>
            <label className={styles.fieldLabel}>預算（NT$）</label>
            <div className={styles.budgetRow}>
              <input
                className={styles.budgetInput}
                type="number"
                placeholder="輸入金額"
                value={form.budget}
                onChange={e => setForm(prev => ({ ...prev, budget: e.target.value }))}
              />
              <div className={styles.chipGroup}>
                {['20,000', '40,000', '60,000', '80,000', '100,000'].map(b => (
                  <button
                    key={b}
                    className={`${styles.chip} ${form.budget === b.replace(',', '') ? styles.chipActive : ''}`}
                    onClick={() => setForm(prev => ({ ...prev, budget: b.replace(/,/g, '') }))}
                  >
                    {b}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* 解析度 */}
          <div className={styles.field}>
            <label className={styles.fieldLabel}>目標解析度</label>
            <div className={styles.chipGroup}>
              {['1080p', '1440p', '4K', '不限'].map(r => (
                <button
                  key={r}
                  className={`${styles.chip} ${form.resolution === r ? styles.chipActive : ''}`}
                  onClick={() => setForm(prev => ({ ...prev, resolution: prev.resolution === r ? '' : r }))}
                >
                  {r}
                </button>
              ))}
            </div>
          </div>

          {/* 品牌偏好（多選） */}
          <div className={styles.field}>
            <label className={styles.fieldLabel}>品牌偏好 <span className={styles.fieldNote}>可多選</span></label>
            <div className={styles.chipGroup}>
              {BRAND_OPTIONS.map(b => (
                <button
                  key={b}
                  className={`${styles.chip} ${form.brand.includes(b) ? styles.chipActive : ''}`}
                  onClick={() => toggleBrand(b)}
                >
                  {b}
                </button>
              ))}
            </div>
          </div>

          {/* 優先考量 */}
          <div className={styles.field}>
            <label className={styles.fieldLabel}>優先考量</label>
            <div className={styles.chipGroup}>
              {PRIORITY_OPTIONS.map(p => (
                <button
                  key={p}
                  className={`${styles.chip} ${form.priority === p ? styles.chipActive : ''}`}
                  onClick={() => setForm(prev => ({ ...prev, priority: prev.priority === p ? '' : p }))}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>

          {/* 其他需求 */}
          <div className={styles.field}>
            <label className={styles.fieldLabel}>其他需求</label>
            <textarea
              className={styles.extraInput}
              placeholder="例如：需要 Wi-Fi 6、機殼要支援 360mm 水冷…"
              rows={2}
              value={form.extra}
              onChange={e => setForm(prev => ({ ...prev, extra: e.target.value }))}
            />
          </div>

          {/* 預覽 + 送出 */}
          <div className={styles.previewWrap}>
            {/*preview ? (
              <div className={styles.preview}>{preview}</div>
            ) : (
              <div className={styles.previewEmpty}>填寫上方條件後，這裡會顯示預覽</div>
            )*/}
            <div className={styles.customActions}>
              <button
                className={styles.clearBtn}
                onClick={() => setForm(DEFAULT_FORM)}
              >
                清除
              </button>
              <button
                className={styles.applyBtn}
                disabled={!preview}
                onClick={handleApply}
              >
                設定偏好
              </button>
            </div>
          </div>

        </div>
      )}

      {/* 快速選擇 */}
      {tab === 'preset' && (
        <div className={styles.presetBody}>
          {PRESET_TEMPLATES.map(group => (
            <div key={group.category} className={styles.group}>
              <div className={styles.groupLabel}>
                {group.icon}
                {group.category}
              </div>
              {group.items.map(item => (
                <button
                  key={item.label}
                  className={styles.presetItem}
                  onClick={() => onSelect(item.text)}
                >
                  <span className={styles.presetLabel}>{item.label}</span>
                  <span className={styles.presetText}>{item.text}</span>
                </button>
              ))}
            </div>
          ))}
        </div>
      )}

    </div>
  )
}
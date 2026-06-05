/**
 * @typedef {
 * 'cpu' |
 * 'gpu' |
 * 'mb' |
 * 'ram' |
 * 'ssd' |
 * 'psu' |
 * 'case' |
 * 'cooler'
 * } PartCategory
 */

/**
 * @typedef {Object} Part
 * @property {string} name              - 零件名稱
 * @property {number} price             - 價格（新台幣）
 * @property {string} detail            - 詳細資訊
 * @property {boolean} [recommended]    - 是否為 AI 推薦
 */

/**
 * @typedef {Object} Parts
 * @property {Part} cpu
 * @property {Part} gpu
 * @property {Part} mb
 * @property {Part} ram
 * @property {Part} ssd
 * @property {Part} psu
 * @property {Part} case
 * @property {Part} cooler
 */

/**
 * @typedef {Object} Build
 * @property {number} id
 * @property {string} name
 * @property {Parts} parts
 * @property {number} budget
 * @property {'電競'|'工作'|'預算'|'創作'} tag
 */

/**
 * @typedef {Object} Message
 * @property {'user'|'assistant'} role
 * @property {string} content
 * @property {string} time
 * @property {string} [ERROR]
 */
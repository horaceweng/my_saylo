import { LEVEL_NAMES, LEVEL_SWATCH, MY_LEVEL_OPTIONS, SEEN_STYLE, levelsShown } from '../lib/wordMarks'

interface Props {
  enabled: boolean
  onEnabled: (on: boolean) => void
  myLevel: number
  onMyLevel: (level: number) => void
}

/** Switch and legend for the difficulty colours: which words are underlined, and what each colour means. */
export default function WordMarksBar({ enabled, onEnabled, myLevel, onMyLevel }: Props) {
  return (
    <div className="mb-6 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl bg-slate-50 px-3 py-2 text-sm dark:bg-slate-800/60" data-marks-bar>
      <label className="flex items-center gap-1.5 font-medium">
        <input type="checkbox" checked={enabled} onChange={(e) => onEnabled(e.target.checked)} />
        單字標色
      </label>
      {enabled && (
        <>
          <label className="flex items-center gap-1.5 text-slate-600 dark:text-slate-300">
            我的程度
            <select
              value={myLevel}
              onChange={(e) => onMyLevel(Number(e.target.value))}
              className="rounded-md border border-slate-300 bg-white px-1.5 py-0.5 dark:border-slate-600 dark:bg-slate-800"
            >
              {MY_LEVEL_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>
          <ul className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500 dark:text-slate-400" aria-label="顏色說明" data-legend>
            {levelsShown(myLevel).map((level) => (
              <li key={level} className="flex items-center gap-1">
                <span className={`inline-block h-0.5 w-4 ${LEVEL_SWATCH[level]}`} />
                {LEVEL_NAMES[level]}
              </li>
            ))}
            <li className="flex items-center gap-1"><span className={`inline-block h-3 w-4 ${SEEN_STYLE}`} />查過／存過</li>
            <li>沒有底線 = 你應該已經會了</li>
          </ul>
        </>
      )}
    </div>
  )
}

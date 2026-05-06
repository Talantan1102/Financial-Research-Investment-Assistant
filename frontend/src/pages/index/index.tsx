import IconBg from '@/assets/index/bg.png'
import IconSearch from '@/assets/index/search.svg'
import { AuditOutlined } from '@ant-design/icons'
import { Button, Input, message } from 'antd'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { INDUSTRY_CONFIGS, setCurrentIndustry } from '@/store/industry'
import { reportActions } from '@/store/report'
import styles from './index.module.scss'

// 行业卡片颜色配置
const INDUSTRY_COLORS: Record<string, { color: string; bgColor: string }> = {
  smart_transportation: { color: '#055588', bgColor: '#E7F4FF' },
  finance: { color: '#1144BA', bgColor: '#EFF3FF' },
  healthcare: { color: '#335519', bgColor: '#EDF7E6' },
  energy: { color: '#B85C00', bgColor: '#FFF4E6' },
}

export default function Index() {
  const navigate = useNavigate()
  const [searchKeyword, setSearchKeyword] = useState('')
  const [targetName, setTargetName] = useState('')
  const [tsCode, setTsCode] = useState('')
  const [starting, setStarting] = useState(false)

  const handleStartResearch = async () => {
    const name = targetName.trim()
    if (!name) {
      message.warning('请输入目标名称')
      return
    }
    setStarting(true)
    try {
      const id = await reportActions.startReport(name, tsCode.trim() || undefined)
      navigate(`/research/${id}`)
    } catch (err) {
      console.error('[Index] startReport failed:', err)
      message.error('启动研报失败,请稍后重试')
    } finally {
      setStarting(false)
    }
  }

  const cardList = useMemo(
    () =>
      INDUSTRY_CONFIGS.map((industry) => ({
        id: industry.id,
        title: `${industry.name}助手`,
        icon: IconSearch,
        desc: industry.description,
        color: INDUSTRY_COLORS[industry.id]?.color || '#333',
        bgColor: INDUSTRY_COLORS[industry.id]?.bgColor || '#f5f5f5',
      })),
    [],
  )

  // 根据搜索关键词过滤卡片
  const filteredCardList = useMemo(() => {
    if (!searchKeyword.trim()) return cardList
    const keyword = searchKeyword.toLowerCase()
    return cardList.filter(
      (item) =>
        item.title.toLowerCase().includes(keyword) ||
        item.desc.toLowerCase().includes(keyword)
    )
  }, [cardList, searchKeyword])

  // 点击卡片，切换行业并跳转到尽调入口（v0.9.x: /chat 已废弃）
  const handleCardClick = (industryId: string, _title: string) => {
    console.log('[Index] 点击行业卡片:', industryId, _title)
    setCurrentIndustry(industryId)
    navigate('/research/new')
  }

  return (
    <div className={styles['index-page']}>
      <div className={styles.header}>
        <img className={styles.bg} src={IconBg} />
        <div className={styles.title}>Hi～欢迎来到行业咨询助手</div>
        <div className={styles.desc}>
          大模型驱动的行业资讯助手，为不同类型用户提供更便捷的AI应用开发平台
        </div>
      </div>

      {/* Task 16 — 投资尽调入口 form (target_name + ts_code → startReport → /research/:id) */}
      <div className={styles['research-entry']}>
        <div className={styles['research-entry__header']}>
          <div className={styles['research-entry__icon']}>
            <AuditOutlined />
          </div>
          <div className={styles['research-entry__heading']}>
            <div className={styles['research-entry__title']}>新建投资尽调研报</div>
            <div className={styles['research-entry__desc']}>
              5-agent 协作产出完整尽调报告 — 覆盖基本面、估值、风险与投资建议
            </div>
          </div>
          <a
            className={styles['research-entry__link']}
            onClick={() => navigate('/research')}
          >
            查看历史研报 →
          </a>
        </div>
        <div className={styles['research-entry__form']}>
          <Input
            placeholder="目标名称(如 贵州茅台)"
            value={targetName}
            onChange={(e) => setTargetName(e.target.value)}
            size="large"
            onPressEnter={handleStartResearch}
            disabled={starting}
          />
          <Input
            placeholder="股票代码(如 600519.SH,可选)"
            value={tsCode}
            onChange={(e) => setTsCode(e.target.value)}
            size="large"
            onPressEnter={handleStartResearch}
            disabled={starting}
          />
          <Button
            type="primary"
            size="large"
            onClick={handleStartResearch}
            loading={starting}
            disabled={!targetName.trim()}
          >
            开始研究
          </Button>
        </div>
      </div>

      <div className={styles['search-bar']}>
        <div className={styles['switch']}>
          <div onClick={() => message.info('暂未开放')} style={{ cursor: 'pointer' }}>我的</div>
          <div className={styles.active}>市场</div>
        </div>

        <div className={styles['search-bar__input']}>
          <Input
            prefix={<img src={IconSearch} />}
            placeholder="搜索应用"
            size="large"
            value={searchKeyword}
            onChange={(e) => setSearchKeyword(e.target.value)}
            allowClear
          />
        </div>
      </div>

      <div className={styles['card-list']}>
        {filteredCardList.length === 0 ? (
          <div style={{ padding: '40px', textAlign: 'center', color: '#999', width: '100%' }}>
            未找到匹配的应用
          </div>
        ) : filteredCardList.map((item) => (
          <div
            className={styles['card-item']}
            key={item.id}
            style={{
              backgroundColor: item.bgColor,
              color: item.color,
              cursor: 'pointer',
            }}
            onClick={() => handleCardClick(item.id, item.title)}
          >
            <div
              className={styles['card-item__icon']}
              style={{
                borderColor: item.color,
              }}
            >
              <img src={item.icon} />
            </div>

            <div className={styles['card-item__title']}>{item.title}</div>
            <div className={styles['card-item__desc']}>{item.desc}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

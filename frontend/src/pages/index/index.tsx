import IconBg from '@/assets/index/bg.png'
import IconSearch from '@/assets/index/search.svg'
import { AuditOutlined, ArrowRightOutlined } from '@ant-design/icons'
import { Input, message } from 'antd'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { INDUSTRY_CONFIGS, setCurrentIndustry } from '@/store/industry'
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

      {/* B-1 CTA banner — 投资标的尽调入口 */}
      <div
        className={styles['cta-banner']}
        onClick={() => navigate('/research/new')}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => e.key === 'Enter' && navigate('/research/new')}
      >
        <div className={styles['cta-banner__icon']}>
          <AuditOutlined />
        </div>
        <div className={styles['cta-banner__content']}>
          <div className={styles['cta-banner__title']}>投资标的尽调</div>
          <div className={styles['cta-banner__desc']}>
            5-agent 协作产出完整尽调报告 — 覆盖基本面、估值、风险与投资建议
          </div>
        </div>
        <div className={styles['cta-banner__arrow']}>
          <ArrowRightOutlined />
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

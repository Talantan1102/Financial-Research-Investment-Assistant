import IconHome from '@/assets/layout/home.svg'
import IconKnowledge from '@/assets/layout/knowledge.svg'
import IconMonitoring from '@/assets/layout/monitoring.svg'
import React, { useMemo } from 'react'
import { useLocation } from 'react-router-dom'
import { useSnapshot } from 'valtio'
import { Dropdown } from 'antd'
import { DownOutlined } from '@ant-design/icons'
import { NavItem } from './nav-item'
import { industryState, setCurrentIndustry } from '@/store/industry'
import './nav.scss'

export function Nav() {
  const { pathname } = useLocation()
  const { currentIndustryId, industries } = useSnapshot(industryState)

  const currentIndustry = useMemo(() => {
    const industry = industries.find((i) => i.id === currentIndustryId)
    console.log('[Nav] 当前行业:', industry?.name)
    return industry || industries[0]
  }, [currentIndustryId, industries])

  const industryMenuItems = useMemo(() => {
    return industries.map((industry) => ({
      key: industry.id,
      label: (
        <div className="industry-menu-item">
          <div className="industry-menu-item__name">{industry.name}</div>
          <div className="industry-menu-item__desc">{industry.description}</div>
        </div>
      ),
      onClick: () => {
        console.log('[Nav] 切换行业:', industry.id, industry.name)
        setCurrentIndustry(industry.id)
      },
    }))
  }, [industries])

  const items = useMemo(
    () => [
      {
        key: 'home',
        label: '首页',
        icon: IconHome,
        href: '/',
      },
      {
        key: 'knowledge',
        label: '知识库',
        icon: IconKnowledge,
        href: '/knowledge',
      },
      {
        key: 'monitoring',
        label: '持仓预警',
        icon: IconMonitoring,
        href: '/monitoring',
      },
      // 暂时隐藏职业规划
      // {
      //   key: 'career',
      //   label: '职业规划',
      //   icon: IconCareer,
      //   href: '#',
      // },
    ],
    [],
  )

  return (
    <>
      {/* 行业选择器 */}
      <div className="industry-selector">
        <Dropdown
          menu={{
            items: industryMenuItems,
            style: { backgroundColor: '#fff' },
          }}
          trigger={['click']}
          placement="bottomLeft"
          dropdownRender={(menu) => (
            <div
              style={{
                backgroundColor: '#fff',
                borderRadius: 8,
                boxShadow: '0 6px 16px 0 rgba(0, 0, 0, 0.08), 0 3px 6px -4px rgba(0, 0, 0, 0.12)',
                padding: 4,
              }}
            >
              {React.cloneElement(menu as React.ReactElement, {
                style: {
                  backgroundColor: '#fff',
                  boxShadow: 'none',
                },
              })}
            </div>
          )}
        >
          <div className="industry-selector__trigger">
            <span className="industry-selector__label">{currentIndustry.name}</span>
            <DownOutlined className="industry-selector__icon" />
          </div>
        </Dropdown>
      </div>

      <div className="base-layout-nav">
        {items.map(({ key, onClick, ...item }) => (
          <NavItem
            key={key}
            {...item}
            active={pathname === item.href}
            onClick={onClick}
          />
        ))}
      </div>
    </>
  )
}

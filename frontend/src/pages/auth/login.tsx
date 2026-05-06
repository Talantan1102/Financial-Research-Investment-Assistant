import * as api from '@/api'
import { authActions } from '@/store/auth'
import { LockOutlined, UserOutlined } from '@ant-design/icons'
import { Button, Form, Input, message } from 'antd'
import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import styles from './login.module.scss'

interface LoginForm {
  username: string
  password: string
}

export default function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [loading, setLoading] = useState(false)

  const from = (location.state as any)?.from?.pathname || '/'

  const onLogin = async (values: LoginForm) => {
    setLoading(true)
    try {
      const { data } = await api.auth.login(values)
      authActions.login(data.access_token, data.user)
      message.success('登录成功')
      navigate(from, { replace: true })
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '登录失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className={styles['auth-page']}>
      <div className={styles['auth-container']}>
        {/* 左侧品牌区域 */}
        <div className={styles['brand-section']}>
          <div className={styles['brand-content']}>
            <h1 className={styles['brand-title']}>AlphaScout</h1>
            <p className={styles['brand-slogan']}>
              Multi-agent Financial Research Platform
            </p>
            <p className={styles['brand-hint']}>
              通用金融 agent 平台 · 投资标的尽调首发场景<br />
              <small style={{ opacity: 0.6 }}>
                假想 banking 风控分析师 demo;欢迎注册体验。
              </small>
            </p>
          </div>
        </div>

        {/* 右侧表单区域 */}
        <div className={styles['form-section']}>
          <div className={styles['form-container']}>
            <div className={styles['form-header']}>
              <h2>登录</h2>
            </div>

            <Form<LoginForm>
              name="login"
              onFinish={onLogin}
              autoComplete="off"
              layout="vertical"
              requiredMark={false}
            >
              <Form.Item
                name="username"
                rules={[
                  { required: true, message: '请输入用户名' },
                  { min: 3, message: '用户名至少 3 个字符' },
                ]}
              >
                <Input
                  prefix={<UserOutlined className={styles['input-icon']} />}
                  placeholder="用户名"
                  size="large"
                  className={styles['form-input']}
                />
              </Form.Item>

              <Form.Item
                name="password"
                rules={[
                  { required: true, message: '请输入密码' },
                  { min: 6, message: '密码至少 6 个字符' },
                ]}
              >
                <Input.Password
                  prefix={<LockOutlined className={styles['input-icon']} />}
                  placeholder="密码"
                  size="large"
                  className={styles['form-input']}
                />
              </Form.Item>

              <Form.Item>
                <Button
                  type="primary"
                  htmlType="submit"
                  loading={loading}
                  block
                  size="large"
                  className={styles['submit-btn']}
                >
                  登录
                </Button>
              </Form.Item>
            </Form>

            <div className={styles['form-footer']}>
              <span className={styles['switch-text']}>没有账号?</span>
              <Link to="/register" className={styles['switch-btn']}>
                立即注册
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

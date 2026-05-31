import { authActions } from '@/store/auth'
import { LockOutlined, MailOutlined, UserOutlined } from '@ant-design/icons'
import { Button, Form, Input } from 'antd'
import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import styles from './login.module.scss'

interface RegisterForm {
  username: string
  email: string
  password: string
}

export default function RegisterPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [loading, setLoading] = useState(false)

  const from = (location.state as any)?.from?.pathname || '/'

  const onRegister = async (values: RegisterForm) => {
    setLoading(true)
    try {
      await authActions.register(values.username, values.password, values.email)
      window.$app.message.success('注册成功')
      navigate(from, { replace: true })
    } catch (error: any) {
      window.$app.message.error(error?.response?.data?.detail || '注册失败')
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
              通用金融 agent 平台<br />
              <small style={{ opacity: 0.6 }}>
                注册后,你的研究记录将与他人完全隔离。
              </small>
            </p>
          </div>
        </div>

        {/* 右侧表单区域 */}
        <div className={styles['form-section']}>
          <div className={styles['form-container']}>
            <div className={styles['form-header']}>
              <h2>注册</h2>
            </div>

            <Form<RegisterForm>
              name="register"
              onFinish={onRegister}
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
                name="email"
                rules={[
                  { required: true, message: '请输入邮箱' },
                  { type: 'email', message: '请输入有效的邮箱地址' },
                ]}
              >
                <Input
                  prefix={<MailOutlined className={styles['input-icon']} />}
                  placeholder="邮箱"
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
                  注册
                </Button>
              </Form.Item>
            </Form>

            <div className={styles['form-footer']}>
              <span className={styles['switch-text']}>已有账号?</span>
              <Link to="/login" className={styles['switch-btn']}>
                直接登录
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

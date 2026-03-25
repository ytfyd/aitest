package com.oddfar.campus.common.domain.model;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;

/**
 * 用户登录对象
 *
 * @author ruoyi
 */
@ApiModel(description = "用户登录对象")
public class LoginBody {
    /**
     * 用户名
     */
    @ApiModelProperty(value = "用户名", example = "admin")
    private String username;

    /**
     * 用户密码
     */
    @ApiModelProperty(value = "用户密码", example = "admin123")
    private String password;

    /**
     * 验证码
     */
    @ApiModelProperty(value = "验证码", example = "1234")
    private String code;

    /**
     * 唯一标识
     */
    @ApiModelProperty(value = "唯一标识", example = "uuid-123456")
    private String uuid;

    public String getUsername() {
        return username;
    }

    public void setUsername(String username) {
        this.username = username;
    }

    public String getPassword() {
        return password;
    }

    public void setPassword(String password) {
        this.password = password;
    }

    public String getCode() {
        return code;
    }

    public void setCode(String code) {
        this.code = code;
    }

    public String getUuid() {
        return uuid;
    }

    public void setUuid(String uuid) {
        this.uuid = uuid;
    }
}

import sys
import os

def main():
    print("🚀 Đang khởi chạy ứng dụng BOTSD Studio Desktop GUI...")
    from desktop_app import BOTSDDesktopApp
    app = BOTSDDesktopApp()
    app.mainloop()

if __name__ == "__main__":
    main()

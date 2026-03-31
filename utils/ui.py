"""
這裡存放的是Notion Cog會用到的discord.ui
"""
import discord

## 注意：不可以在這邊import Cog ##
# parent_cog 就是 Notion Cog
# 因為我們要用的_function在Notion Cog裡面

# Modal
class AddInfoModal(discord.ui.Modal, title="補充書籍資訊"):
    # define every property
    author = discord.ui.TextInput(
        label='作者',
        placeholder='如果不清楚可空著...',
        required=False
    )
    source = discord.ui.TextInput(
        label='來源',
        placeholder="圖書館實體書/電子書/pdf",
        required=False
    )
    remark = discord.ui.TextInput(
        label='備註',
        style=discord.TextStyle.paragraph, #可以輸入較長文本的文字框
        required=False,
        max_length=200
    )

    #
    def __init__(self, parent_cog, title, content, status):
        super().__init__()
        self.parent_cog = parent_cog
        self.book_title = title # differ oto Modal title
        self.content = content
        self.status = status

    # on_submit也是預設的function
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()

        async with interaction.channel.typing():
            new_page = await self.parent_cog._notion_create_note(
                title=self.book_title,
                author=self.author.value or None,
                status=self.status,
                source=self.source.value or "圖書館實體書",
                remark=self.remark.value or None
            )

            if self.content:
                await self.parent_cog._append_content(page_id=new_page['id'], content=self.content)
            
            await interaction.followup.send(f"已經幫你新增《{self.book_title}》了！")
    

# UI View

class ConfirmAddView(discord.ui.View):
    """當update找不到資料時，詢問是否要新增"""
    def __init__(self, parent_cog, title, content, status): #改成params?吧
        super().__init__(timeout=60) # 60秒後 按鈕失效
        self.parent_cog = parent_cog
        self.title = title
        self.content = content
        self.status = status

    @discord.ui.button(label="直接新增這本書", style=discord.ButtonStyle.green, emoji="➕")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        # button.disabled = True # 改變按鈕狀態
        # await interaction.response.edit_message(view=self)
        # 因為一個interaction只能response一次，如果edit_message後又做下面的send_modal會爆掉

        # 叫出Modal來補全書本資料
        modal = AddInfoModal(self.parent_cog, self.title, self.content, self.status)
        await interaction.response.send_modal(modal)
        
    
    # 不用等到timeuot 也可以直接按取消
    @discord.ui.button(label="取消", style=discord.ButtonStyle.grey)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("已取消", ephemeral=True, view=None)
        self.stop()
    

class ConfirmUpdateView(discord.ui.View):
    """當要新增時發現已經有資料，問要不要update"""
    def __init__(self, parent_cog, page_id, title, content=None, status=None):
        super().__init__(timeout=60)
        self.parent_cog = parent_cog
        self.page_id = page_id
        self.title = title
        self.content = content
        self.status = status
    
    @discord.ui.button(label="更新現有書籍", style=discord.ButtonStyle.green)
    async def update_existing(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        async with interaction.channel.typing():
            # update status
            if self.status:
                await self.parent_cog._notion_update_properties(self.page_id, self.status)

            if self.content:
                await self.parent_cog._append_content(self.page_id, self.content)

        await interaction.followup.send(f"已更新《{self.title}》")
        self.stop()
    
    @discord.ui.button(label="不，請新增一本書", style=discord.ButtonStyle.blurple)
    async def add_new_duplicate(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 一樣跳出來讓使用者補充作者來源和備註
        modal = AddInfoModal(self.parent_cog, self.title, self.content, self.status)
        await interaction.response.send_modal(modal)
        self.stop()
    
    @discord.ui.button(label="取消", style=discord.ButtonStyle.grey)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="已取消", ephemeral=True, view=None)
        self.stop()
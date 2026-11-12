from libero_env import LiberoEnv
env=LiberoEnv()
if env.tries_left<=0: raise RuntimeError('No trials remaining')
obs=env.reset()
def cmd(x,y,z,g,n=30):
 global obs
 for _ in range(n): obs,r,d,i=env.step([x,y,z,0,0,0,g])
def pick(obj):
 p=obs['objects'][obj]['pos'][:]
 cmd(p[0],p[1],p[2]+.15,-1,30)
 cmd(p[0],p[1],p[2],-1,30)
 cmd(p[0],p[1],p[2],1,40)
 cmd(p[0],p[1],p[2]+.23,1,30)
 print('grasp check',obj,obs['objects'][obj]['pos'],obs['eef_pos'])
def put(obj):
 b=obs['objects']['basket_1']['pos'][:]
 cmd(b[0],b[1],b[2]+.24,1,35)
 b=obs['objects']['basket_1']['pos'][:]
 cmd(b[0],b[1],b[2]+.16,1,25)
 cmd(b[0],b[1],b[2]+.16,-1,35)
 cmd(b[0],b[1],b[2]+.27,-1,25)
 print('placed',obj,obs['objects'][obj]['pos'],'basket',obs['objects']['basket_1']['pos'],env.check_success())
for name in ['cream_cheese_1','butter_1']:
 pick(name)
 put(name)
 if env.check_success(): break
print('success',env.check_success(),'left',env.tries_left)
